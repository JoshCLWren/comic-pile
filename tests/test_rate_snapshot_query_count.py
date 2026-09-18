"""Query-count regression tests for legacy full snapshot capture.

Issue #2611: the legacy full snapshot in ``snapshot_thread_states`` captured
each thread's pre-state with an individual ``select(Issue)`` per issue-tracked
thread, an N+1 pattern that grows with the thread count. These tests prove the
full snapshot now loads every thread's issues in a single batched query and
that the serialized issue states are unchanged.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Event, Issue, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.user import User
from app.services.rate_service import snapshot_thread_states


async def _seed_tracked_and_untracked_threads(
    async_db: AsyncSession,
    user: User,
    thread_count: int,
) -> list[Thread]:
    """Create issue-tracking threads (with Issue rows) plus one legacy thread.

    Args:
        async_db: Database session.
        user: Thread owner.
        thread_count: Number of issue-tracking threads to create.

    Returns:
        All created threads in insertion order.
    """
    tracked_threads = [
        Thread(
            title=f"Tracked {i}",
            format="Comic",
            issues_remaining=3,
            queue_position=i + 1,
            status="active",
            user_id=user.id,
            total_issues=3,
            reading_progress="in_progress",
            last_activity_at=datetime.now(UTC),
        )
        for i in range(thread_count)
    ]
    async_db.add_all(tracked_threads)
    await async_db.flush()

    for thread in tracked_threads:
        issues = [
            Issue(
                thread_id=thread.id,
                issue_number=str(issue_number),
                position=issue_number,
                status="read" if issue_number == 1 else "unread",
                read_at=datetime.now(UTC) if issue_number == 1 else None,
            )
            for issue_number in range(1, 4)
        ]
        async_db.add_all(issues)
        await async_db.flush()
        thread.next_unread_issue_id = issues[1].id

    legacy_thread = Thread(
        title="Legacy",
        format="Comic",
        issues_remaining=5,
        queue_position=thread_count + 1,
        status="active",
        user_id=user.id,
    )
    async_db.add(legacy_thread)
    await async_db.flush()
    return [*tracked_threads, legacy_thread]


@pytest.mark.asyncio
@pytest.mark.parametrize("thread_count", [1, 20])
async def test_full_snapshot_issue_loads_are_constant(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    thread_count: int,
) -> None:
    """Full snapshot issue reads stay at one query as thread count grows."""
    threads = await _seed_tracked_and_untracked_threads(
        async_db, default_user, thread_count
    )

    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.flush()
    event = Event(type="rate", session_id=session.id, rating=4.0)
    async_db.add(event)
    await async_db.flush()

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
        await snapshot_thread_states(
            async_db,
            session.id,
            event.id,
            default_user.id,
            commit=False,
        )
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    issue_reads = [s for s in statements if "from issues" in s.lower()]
    assert len(issue_reads) == 1, (
        f"Expected a single batched issue select, got {len(issue_reads)}: {issue_reads}"
    )

    await async_db.flush()
    snapshot_result = await async_db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session.id)
        .where(Snapshot.event_id == event.id)
        .order_by(Snapshot.id.desc())
    )
    snapshot = snapshot_result.scalar_one()

    assert set(snapshot.thread_states) >= {str(t.id) for t in threads}
    for thread in threads[:-1]:
        issue_states = snapshot.thread_states[str(thread.id)]["issue_states"]
        assert [state["number"] for state in issue_states] == ["1", "2", "3"]
        assert [state["position"] for state in issue_states] == [1, 2, 3]
        assert [state["status"] for state in issue_states] == [
            "read",
            "unread",
            "unread",
        ]

    legacy_state = snapshot.thread_states[str(threads[-1].id)]
    assert legacy_state["issue_states"] is None
    assert legacy_state["total_issues"] is None
