"""Tests linking rate events to their exact originating roll events."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models import ReadingSession


async def _latest_rate_event(async_db: AsyncSession, session_id: int) -> Event:
    """Fetch the newest rate event for a session."""
    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type == "rate")
        .order_by(Event.timestamp.desc(), Event.id.desc())
    )
    rate_event = result.scalars().first()
    assert rate_event is not None
    return rate_event


async def _create_thread(async_db: AsyncSession, user_id: int, title: str) -> Thread:
    """Create one active thread owned by the user."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user_id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)
    return thread


async def _roll_via_api(
    auth_client: AsyncClient, async_db: AsyncSession
) -> tuple[ReadingSession, Event]:
    """Roll through the API and return the authoritative session and roll event."""
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200

    session_result = await async_db.execute(
        select(ReadingSession).where(ReadingSession.ended_at.is_(None))
    )
    session = session_result.scalars().first()
    assert session is not None
    assert session.pending_thread_id is not None

    event_result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id == session.pending_thread_id)
        .order_by(Event.timestamp.desc(), Event.id.desc())
    )
    roll_event = event_result.scalars().first()
    assert roll_event is not None
    return session, roll_event


@pytest.mark.asyncio
async def test_event_model_round_trips_linked_and_unlinked_source_roll(
    async_db: AsyncSession,
) -> None:
    """Linked and unlinked events store and reload their source-roll linkage."""
    linked_roll = Event(type="roll", selected_thread_id=1, selection_method="random")
    async_db.add(linked_roll)
    await async_db.flush()

    linked_rate = Event(type="rate", source_roll_event_id=linked_roll.id)
    unlinked_rate = Event(type="rate")
    async_db.add_all([linked_rate, unlinked_rate])
    await async_db.commit()

    reloaded_linked = await async_db.get(Event, linked_rate.id)
    reloaded_unlinked = await async_db.get(Event, unlinked_rate.id)
    assert reloaded_linked is not None
    assert reloaded_unlinked is not None
    assert reloaded_linked.source_roll_event_id == linked_roll.id
    assert reloaded_unlinked.source_roll_event_id is None


@pytest.mark.asyncio
async def test_invalid_source_roll_reference_rejected_by_database_contract(
    async_db: AsyncSession,
) -> None:
    """Foreign-key contract rejects source-roll references to missing events."""
    from sqlalchemy.exc import IntegrityError

    orphan_rate = Event(type="rate", source_roll_event_id=99999999)
    async_db.add(orphan_rate)
    with pytest.raises(IntegrityError):
        await async_db.flush()
    await async_db.rollback()


@pytest.mark.asyncio
async def test_deleting_originating_roll_nulls_source_roll_reference(
    async_db: AsyncSession,
) -> None:
    """Removing the roll event nulls the reference instead of cascading deletes."""
    linked_roll = Event(type="roll", selected_thread_id=1, selection_method="random")
    async_db.add(linked_roll)
    await async_db.flush()

    linked_rate = Event(type="rate", source_roll_event_id=linked_roll.id)
    async_db.add(linked_rate)
    await async_db.commit()

    await async_db.delete(linked_roll)
    await async_db.commit()

    surviving_rate = await async_db.get(Event, linked_rate.id)
    assert surviving_rate is not None
    async_db.expire(surviving_rate)
    await async_db.refresh(surviving_rate)
    assert surviving_rate.source_roll_event_id is None
