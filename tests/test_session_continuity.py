"""Regression coverage for reading-session continuity across auth/bootstrap recovery."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, Thread, User
from comic_pile.session import get_or_create, should_start_new


@pytest.mark.asyncio
async def test_recent_pending_roll_keeps_old_open_session_authoritative(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A recently pending comic must survive after the session start crosses the gap."""
    thread = Thread(
        title="Fantastic Four",
        format="Comic",
        issues_remaining=6,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    async_db.add(thread)
    await async_db.flush()

    original_session = Session(
        user_id=default_user.id,
        started_at=datetime.now(UTC) - timedelta(hours=7),
        start_die=6,
        manual_die=20,
        pending_thread_id=thread.id,
        pending_thread_updated_at=datetime.now(UTC) - timedelta(minutes=10),
        snoozed_thread_ids=[thread.id + 1, thread.id + 2],
    )
    async_db.add(original_session)
    await async_db.commit()

    assert await should_start_new(async_db, default_user.id) is False

    recovered_session = await get_or_create(async_db, default_user.id)

    assert recovered_session.id == original_session.id
    assert recovered_session.pending_thread_id == thread.id
    assert recovered_session.manual_die == 20
    assert recovered_session.snoozed_thread_ids == [thread.id + 1, thread.id + 2]

    open_count = await async_db.scalar(
        select(func.count())
        .select_from(Session)
        .where(Session.user_id == default_user.id)
        .where(Session.ended_at.is_(None))
    )
    assert open_count == 1


@pytest.mark.asyncio
async def test_stale_session_without_recent_pending_activity_can_roll_over(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The configured session gap still starts a new session after genuinely stale activity."""
    thread = Thread(
        title="Old Pending Comic",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    async_db.add(thread)
    await async_db.flush()

    stale_session = Session(
        user_id=default_user.id,
        started_at=datetime.now(UTC) - timedelta(hours=8),
        start_die=6,
        pending_thread_id=thread.id,
        pending_thread_updated_at=datetime.now(UTC) - timedelta(hours=7),
    )
    async_db.add(stale_session)
    await async_db.commit()

    assert await should_start_new(async_db, default_user.id) is True

    new_session = await get_or_create(async_db, default_user.id)

    assert new_session.id != stale_session.id
    assert new_session.pending_thread_id is None
    assert new_session.start_die == 6
