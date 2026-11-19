"""Tests for Phase 0 instrumentation: issue snapshots on roll events.

Covers:
- #1689: issue_id/issue_number populated on roll events
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models import ReadingSession


@pytest.mark.asyncio
async def test_existing_events_with_null_source_roll_load_normally(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Historical events with NULL source_roll_event_id continue to work."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Legacy Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    legacy_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.0,
        die=10,
        die_after=8,
    )
    async_db.add(legacy_event)
    await async_db.commit()

    result = await async_db.execute(select(Event).where(Event.id == legacy_event.id))
    loaded = result.scalar_one()
    assert loaded.source_roll_event_id is None
