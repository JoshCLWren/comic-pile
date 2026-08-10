"""Regression coverage for deterministic current-session resolution."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Session, Thread, User
from comic_pile.session import get_or_create, resolve_current_session, should_start_new


@pytest.mark.asyncio
async def test_pending_activity_keeps_long_running_session_current(
    async_db: AsyncSession, default_user: User
) -> None:
    """A recent pending roll keeps a session current even when it started hours ago."""
    session = Session(
        started_at=datetime.now(UTC) - timedelta(hours=7),
        pending_thread_updated_at=datetime.now(UTC) - timedelta(minutes=5),
        start_die=12,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    resolved = await get_or_create(async_db, default_user.id)

    assert resolved.id == session.id
    assert resolved.start_die == 12
    assert await should_start_new(async_db, default_user.id) is False


@pytest.mark.asyncio
async def test_pending_session_beats_newer_blank_duplicate(
    async_db: AsyncSession, default_user: User
) -> None:
    """A pending comic remains authoritative over a later blank duplicate session."""
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

    reading_session = Session(
        started_at=datetime.now(UTC) - timedelta(hours=7),
        pending_thread_id=thread.id,
        pending_thread_updated_at=datetime.now(UTC) - timedelta(minutes=10),
        start_die=20,
        user_id=default_user.id,
    )
    blank_session = Session(
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
    assert resolved.id == reading_session.id
    assert resolved.pending_thread_id == thread.id
    assert resolved.id != blank_session.id


@pytest.mark.asyncio
async def test_recent_reading_activity_beats_older_blank_unended_session(
    async_db: AsyncSession, default_user: User
) -> None:
    """Recent durable activity wins when competing sessions have no pending context."""
    reading_session = Session(
        started_at=datetime.now(UTC) - timedelta(hours=5),
        start_die=20,
        user_id=default_user.id,
    )
    blank_session = Session(
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
    assert resolved.id == reading_session.id
    assert resolved.id != blank_session.id


@pytest.mark.asyncio
async def test_stale_unended_history_does_not_prevent_new_session(
    async_db: AsyncSession, default_user: User
) -> None:
    """Unended historical rows outside the activity gap remain history, not current."""
    stale_session = Session(
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
