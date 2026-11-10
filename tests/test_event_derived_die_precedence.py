"""Event-derived die precedence (#4352, #4405).

A manual die choice is one explicit event, not a permanent
``sessions.manual_die`` pin. These focused regressions pin the reader
contract shared by the Python Roll paths and the Rust bootstrap:

* the newest die event wins whenever die events exist;
* the legacy ``manual_die`` column is only a fallback when no die
  events exist (preserving pre-cutover selections that were written
  column-only by the retired v1 set-die route).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Thread, User
from comic_pile.reading_session import get_current_die, get_current_die_for_session


@pytest.mark.asyncio
async def test_owner_reader_uses_sessionless_native_event_over_column(
    async_db: AsyncSession, default_user: User
) -> None:
    """A Rust sessionless manual_die event is not overridden by the old column pin."""
    session = ReadingSession(
        start_die=6,
        manual_die=20,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    now = datetime.now(UTC)
    async_db.add(
        Event(
            type="manual_die",
            user_id=default_user.id,
            die_after=12,
            timestamp=now,
            context={"dice_command_key": "client-command-123"},
        )
    )
    await async_db.commit()

    assert await get_current_die_for_session(session, async_db) == 12


@pytest.mark.asyncio
async def test_owner_reader_uses_legacy_rate_event_over_column(
    async_db: AsyncSession, default_user: User
) -> None:
    """A legacy session rate event unpins the manual_die column once dice moved."""
    session = ReadingSession(
        start_die=6,
        manual_die=20,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    thread = Thread(
        title="Event Die Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add_all([session, thread])
    await async_db.commit()
    await async_db.refresh(session)
    await async_db.refresh(thread)

    async_db.add(
        Event(
            type="rate",
            session_id=session.id,
            thread_id=thread.id,
            user_id=default_user.id,
            rating=3.0,
            die_after=8,
            timestamp=datetime.now(UTC),
        )
    )
    await async_db.commit()

    assert await get_current_die_for_session(session, async_db) == 8


@pytest.mark.asyncio
async def test_session_scoped_reader_uses_event_over_column(
    async_db: AsyncSession, default_user: User
) -> None:
    """The session-scoped reader mirrors the owner-scoped event-derived die."""
    session = ReadingSession(
        start_die=6,
        manual_die=20,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    thread = Thread(
        title="Session Scoped Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add_all([session, thread])
    await async_db.commit()
    await async_db.refresh(session)
    await async_db.refresh(thread)

    async_db.add(
        Event(
            type="snooze",
            session_id=session.id,
            thread_id=thread.id,
            die_after=10,
            timestamp=datetime.now(UTC) + timedelta(seconds=1),
        )
    )
    await async_db.commit()

    assert await get_current_die(session.id, async_db) == 10


@pytest.mark.asyncio
async def test_column_remains_fallback_without_die_events(
    async_db: AsyncSession, default_user: User
) -> None:
    """Pre-cutover column-only selections are preserved until a die event exists."""
    session = ReadingSession(
        start_die=6,
        manual_die=20,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    assert await get_current_die(session.id, async_db) == 20
    assert await get_current_die_for_session(session, async_db) == 20
