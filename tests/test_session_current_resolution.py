"""Regression coverage for deterministic current-session resolution."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Thread, User
from comic_pile.reading_session import get_or_create, resolve_current_session, should_start_new


@pytest.mark.asyncio
async def test_pending_activity_does_not_extend_six_hour_session(
    async_db: AsyncSession, default_user: User
) -> None:
    """A recent pending roll does not extend a six-hour session."""
    thread = Thread(
        title="Pending Activity",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    async_db.add(thread)
    await async_db.flush()

    session = ReadingSession(
        started_at=datetime.now(UTC) - timedelta(hours=7),
        pending_thread_id=thread.id,
        pending_thread_updated_at=datetime.now(UTC) - timedelta(minutes=5),
        start_die=12,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    resolved = await get_or_create(async_db, default_user.id)

    assert resolved.id != session.id
    assert resolved.start_die == 6
    assert await should_start_new(async_db, default_user.id) is False


@pytest.mark.asyncio
async def test_expired_pending_session_does_not_beat_newer_session(
    async_db: AsyncSession, default_user: User
) -> None:
    """A pending comic in an expired session cannot override a newer session."""
    thread = Thread(
        title="Fantastic Four",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    async_db.add(thread)
    await async_db.flush()

    reading_session = ReadingSession(
        started_at=datetime.now(UTC) - timedelta(hours=7),
        pending_thread_id=thread.id,
        pending_thread_updated_at=datetime.now(UTC) - timedelta(minutes=10),
        start_die=20,
        user_id=default_user.id,
    )
    blank_session = ReadingSession(
        started_at=datetime.now(UTC) - timedelta(minutes=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add_all([reading_session, blank_session])
    await async_db.flush()
    async_db.add(
        Event(
            type="roll",
            timestamp=datetime.now(UTC) - timedelta(minutes=10),
            session_id=reading_session.id,
            selected_thread_id=thread.id,
            die=20,
            result=4,
            selection_method="random",
        )
    )
    await async_db.commit()

    resolved = await resolve_current_session(async_db, default_user.id)

    assert resolved is not None
    assert resolved.id == blank_session.id
    assert resolved.pending_thread_id is None
    assert resolved.id != reading_session.id


@pytest.mark.asyncio
async def test_recent_events_do_not_override_newer_session(
    async_db: AsyncSession, default_user: User
) -> None:
    """The newest unended session wins irrespective of activity on older sessions."""
    reading_session = ReadingSession(
        started_at=datetime.now(UTC) - timedelta(hours=5),
        start_die=20,
        user_id=default_user.id,
    )
    blank_session = ReadingSession(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add_all([reading_session, blank_session])
    await async_db.flush()
    async_db.add(
        Event(
            type="rate",
            timestamp=datetime.now(UTC) - timedelta(minutes=2),
            session_id=reading_session.id,
            die=20,
            die_after=30,
        )
    )
    await async_db.commit()

    resolved = await resolve_current_session(async_db, default_user.id)

    assert resolved is not None
    assert resolved.id == blank_session.id
    assert resolved.id != reading_session.id


@pytest.mark.asyncio
async def test_stale_unended_history_does_not_prevent_new_session(
    async_db: AsyncSession, default_user: User
) -> None:
    """Unended historical rows outside the activity gap remain history, not current."""
    stale_session = ReadingSession(
        started_at=datetime.now(UTC) - timedelta(hours=9),
        start_die=10,
        user_id=default_user.id,
    )
    async_db.add(stale_session)
    await async_db.commit()

    assert await resolve_current_session(async_db, default_user.id) is None
    assert await should_start_new(async_db, default_user.id) is True

    created = await get_or_create(async_db, default_user.id)
    assert created.id != stale_session.id
    assert created.start_die == 6


@pytest.mark.asyncio
async def test_session_expiry_ignores_recent_events_and_future_start(
    async_db: AsyncSession, default_user: User
) -> None:
    """An unended old session expires even when it has fresh activity."""
    now = datetime.now(UTC)
    old = ReadingSession(
        user_id=default_user.id,
        started_at=now - timedelta(hours=6, minutes=1),
        start_die=12,
    )
    future = ReadingSession(
        user_id=default_user.id,
        started_at=now + timedelta(hours=1),
        start_die=20,
    )
    async_db.add_all([old, future])
    await async_db.flush()
    async_db.add(Event(
        session_id=old.id,
        type="rate",
        timestamp=now,
        die=12,
        die_after=20,
    ))
    await async_db.commit()
    assert await resolve_current_session(async_db, default_user.id) is None
    created = await get_or_create(async_db, default_user.id)
    assert created.id not in {old.id, future.id}
    assert created.start_die == 6


@pytest.mark.asyncio
async def test_session_before_expiry_remains_active(
    async_db: AsyncSession, default_user: User
) -> None:
    """An unended 5h59m session remains active in its original window."""
    current = ReadingSession(
        user_id=default_user.id,
        started_at=datetime.now(UTC) - timedelta(hours=5, minutes=59),
        start_die=8,
    )
    async_db.add(current)
    await async_db.commit()
    assert (await resolve_current_session(async_db, default_user.id)).id == current.id
