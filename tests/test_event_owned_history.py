"""Session-independent event ownership and historical retention (#4405)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, User


@pytest.mark.asyncio
async def test_direct_history_is_owner_scoped_without_a_reading_session(
    async_db: AsyncSession, default_user: User
) -> None:
    other = User(username="another_event_history_reader")
    async_db.add(other)
    await async_db.flush()

    old_session = ReadingSession(user_id=default_user.id)
    async_db.add(old_session)
    await async_db.flush()
    previous = Event(
        type="rate", session_id=old_session.id, user_id=default_user.id,
        rating=4.5, die=6, die_after=4,
    )
    direct = Event(
        type="mark_read", user_id=default_user.id,
        rating=3.5, die_after=None,
    )
    private = Event(
        type="reset_dice", user_id=other.id, die_after=6,
    )
    async_db.add_all([previous, direct, private])
    await async_db.commit()

    result = await async_db.scalars(
        select(Event).where(Event.user_id == default_user.id).order_by(Event.id)
    )
    assert [event.id for event in result.all()] == [previous.id, direct.id]
    assert direct.session_id is None
    assert private.user_id == other.id


@pytest.mark.asyncio
async def test_deleting_session_preserves_owned_event(
    async_db: AsyncSession, default_user: User
) -> None:
    legacy_session = ReadingSession(user_id=default_user.id)
    async_db.add(legacy_session)
    await async_db.flush()
    original = Event(
        type="snooze", session_id=legacy_session.id,
        user_id=default_user.id, die=6, die_after=8,
    )
    async_db.add(original)
    await async_db.commit()
    original_id = original.id

    await async_db.delete(legacy_session)
    await async_db.commit()
    preserved = await async_db.get(Event, original_id, populate_existing=True)

    assert preserved is not None
    assert preserved.user_id == default_user.id
    assert preserved.session_id is None
    assert (preserved.type, preserved.die_after) == ("snooze", 8)
