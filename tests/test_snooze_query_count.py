"""Query-count regression tests for snooze response building.

Issue #1257: ``build_session_response`` previously loaded each snoozed
thread with one ``db.get(Thread)`` per ID, an N+1 pattern that grows with
the snoozed list. These tests prove it now loads all snoozed threads in a
single query regardless of how many are snoozed, and that the response
contract (ordered ``snoozed_threads``) is unchanged.
"""

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.snooze import build_session_response
from app.models import Thread, User
from app.models import Session as SessionModel


@pytest.mark.asyncio
@pytest.mark.parametrize("thread_count", [1, 20])
async def test_build_session_response_snoozed_thread_reads_are_constant(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    thread_count: int,
) -> None:
    """Snoozed-thread reads stay at one query as the snoozed list grows."""
    threads = [
        Thread(
            title=f"Snoozed {i}",
            format="Comic",
            issues_remaining=10,
            queue_position=i + 1,
            user_id=default_user.id,
        )
        for i in range(thread_count)
    ]
    async_db.add_all(threads)
    await async_db.flush()
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        snoozed_thread_ids=[t.id for t in threads],
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(str(statement))

    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        response = await build_session_response(session, async_db)
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    assert [t.id for t in response.snoozed_threads] == [t.id for t in threads]
    assert [t.title for t in response.snoozed_threads] == [t.title for t in threads]

    thread_reads = [s for s in statements if "from threads" in s.lower()]
    assert len(thread_reads) == 1, (
        f"Expected a single bulk thread read, got {len(thread_reads)}: {thread_reads}"
    )
