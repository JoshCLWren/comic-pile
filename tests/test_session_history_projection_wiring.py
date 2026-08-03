"""Endpoint-level regression coverage for the linear History event projection.

These tests prove ``list_sessions()`` preserves the exact History response
contract when it assembles summaries from the single ordered event read
produced by ``project_session_history_events()``.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread, User
from app.models import Session as SessionModel


async def _commit_all(async_db: AsyncSession) -> None:
    await async_db.flush()
    await async_db.commit()


def _roll_event(
    session: SessionModel,
    thread: Thread,
    *,
    timestamp: int,
    thread_id: int | None = None,
) -> Event:
    """Build a roll event for a fixed deterministic wall clock."""
    return Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        thread_id=thread_id,
        die=session.start_die,
        result=timestamp,
        selection_method="random",
        timestamp=datetime(2026, 8, 2, 12, 0, timestamp, tzinfo=UTC),
    )


def _die_event(
    session: SessionModel,
    thread: Thread,
    *,
    timestamp: int,
    die_after: int,
) -> Event:
    """Build a rate/snooze die-transition event at a fixed wall clock."""
    return Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        die_after=die_after,
        timestamp=datetime(2026, 8, 2, 12, 0, timestamp, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_history_ladder_is_chronological_and_current_die_uses_latest(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Ladder order stays chronological and current_die uses the newest event."""
    thread = Thread(
        title="Ladder Comic",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.flush()
    async_db.add_all(
        [
            _die_event(session, thread, timestamp=1, die_after=8),
            _die_event(session, thread, timestamp=2, die_after=12),
            _die_event(session, thread, timestamp=3, die_after=10),
        ]
    )
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["ladder_path"] == "6 → 8 → 12 → 10"
    assert item["current_die"] == 10
    assert item["start_die"] == 6


@pytest.mark.asyncio
async def test_history_manual_die_overrides_event_derived_die(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A manual die takes precedence over event-derived current die."""
    thread = Thread(
        title="Manual Die Comic",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    session = SessionModel(
        start_die=6,
        manual_die=20,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.flush()
    async_db.add(_die_event(session, thread, timestamp=1, die_after=8))
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["current_die"] == 20
    assert item["manual_die"] == 20
    assert item["ladder_path"] == "6 → 8"


@pytest.mark.asyncio
async def test_history_no_die_events_falls_back_to_start_die(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Sessions without die events fall back to the start die for ladder and die."""
    session = SessionModel(start_die=10, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["ladder_path"] == "10"
    assert item["current_die"] == 10


@pytest.mark.asyncio
async def test_history_latest_roll_wins_when_multiple_rolls_exist(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Latest roll selection uses event order and returns the newest thread."""
    thread_a = Thread(
        title="First Comic",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    thread_b = Thread(
        title="Second Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        user_id=default_user.id,
    )
    async_db.add_all([thread_a, thread_b])
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.flush()
    async_db.add_all(
        [
            _roll_event(session, thread_a, timestamp=1),
            _roll_event(session, thread_b, timestamp=2),
        ]
    )
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["active_thread"] is not None
    assert item["active_thread"]["title"] == "Second Comic"
    assert item["last_rolled_result"] == 2


@pytest.mark.asyncio
async def test_history_deleted_thread_yields_null_active_thread(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Rolls referencing a deleted thread produce active_thread=None."""
    thread = Thread(
        title="Doomed Comic",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.flush()
    await _commit_all(async_db)

    async_db.add(_roll_event(session, thread, timestamp=1, thread_id=None))
    await _commit_all(async_db)

    await async_db.delete(thread)
    await _commit_all(async_db)
    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["active_thread"] is None
    assert item["last_rolled_result"] is None


@pytest.mark.asyncio
async def test_history_event_reads_do_not_grow_per_session(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine,
    default_user: User,
) -> None:
    """The History page performs one events read regardless of page size."""
    for i in range(5):
        thread = Thread(
            title=f"Comic {i}",
            format="Comic",
            issues_remaining=10,
            queue_position=i + 1,
            user_id=default_user.id,
        )
        async_db.add(thread)
        session = SessionModel(
            start_die=6,
            user_id=default_user.id,
            started_at=datetime(2026, 8, 2, 12, 0, i, tzinfo=UTC),
        )
        async_db.add(session)
        await _commit_all(async_db)
        async_db.add(_roll_event(session, thread, timestamp=i))
        async_db.add(_die_event(session, thread, timestamp=i, die_after=8 + i))
        await _commit_all(async_db)

    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        response = await auth_client.get("/api/sessions/?page_size=50")
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert len(response.json()["sessions"]) == 5

    event_reads = [s for s in statements if "from events" in s.lower()]
    assert len(event_reads) == 1, (
        f"Expected a single events read, got {len(event_reads)}: {event_reads}"
    )
