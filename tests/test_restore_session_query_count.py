"""Query-count regression tests for restore-session-start.

Issue #1257: ``restore_session_start`` previously recomputed per-thread
unread counts with one COUNT query per migrated thread (plus a dead
per-thread positions read that always followed a DELETE). These tests prove
the endpoint now issues a single grouped COUNT and no per-thread issue reads
regardless of how many migrated threads are restored.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Issue, Thread, User
from app.models import Session as SessionModel
from comic_pile.session import create_session_start_snapshot


async def _seed_migrated_session(
    async_db: AsyncSession,
    user_id: int,
    thread_count: int,
) -> SessionModel:
    """Create a session with ``thread_count`` migrated threads and a start snapshot."""
    session = SessionModel(start_die=6, user_id=user_id)
    async_db.add(session)
    await async_db.flush()
    for i in range(thread_count):
        thread = Thread(
            title=f"Bulk {i}",
            format="Comic",
            issues_remaining=0,
            queue_position=i + 1,
            user_id=user_id,
            total_issues=5,
            reading_progress="in_progress",
        )
        async_db.add(thread)
        await async_db.flush()
        first_issue = None
        for j in range(1, 6):
            issue = Issue(
                thread_id=thread.id,
                issue_number=str(j),
                position=j,
                status="unread" if j <= 2 else "read",
            )
            async_db.add(issue)
            if first_issue is None:
                first_issue = issue
        assert first_issue is not None
        thread.next_unread_issue_id = first_issue.id
    await async_db.flush()
    await create_session_start_snapshot(async_db, session)
    await async_db.refresh(session)
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize("thread_count", [1, 20])
async def test_restore_recounts_are_bulk_constant(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    thread_count: int,
) -> None:
    """Restore uses one grouped COUNT and zero per-thread issue reads."""
    session = await _seed_migrated_session(async_db, default_user.id, thread_count)

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
        response = await auth_client.post(f"/api/sessions/{session.id}/restore-session-start")
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200

    per_thread_counts = [
        s
        for s in statements
        if "count(" in s.lower()
        and "from issues" in s.lower()
        and "group by" not in s.lower()
    ]
    assert per_thread_counts == [], (
        f"Found per-thread COUNT queries: {per_thread_counts}"
    )

    bulk_counts = [s for s in statements if "group by" in s.lower() and "issues" in s.lower()]
    assert len(bulk_counts) == 1, (
        f"Expected 1 bulk COUNT query, got {len(bulk_counts)}: {bulk_counts}"
    )

    per_thread_issue_reads = [
        s
        for s in statements
        if s.lower().startswith("select")
        and "from issues" in s.lower()
        and "issues.thread_id =" in s.lower()
        and "group by" not in s.lower()
    ]
    assert per_thread_issue_reads == [], (
        f"Found per-thread issue reads: {per_thread_issue_reads}"
    )
