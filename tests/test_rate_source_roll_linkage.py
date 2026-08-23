"""Tests linking rate events to their exact originating roll events."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models import Session as SessionModel


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
) -> tuple[SessionModel, Event]:
    """Roll through the API and return the authoritative session and roll event."""
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200

    session_result = await async_db.execute(
        select(SessionModel).where(SessionModel.ended_at.is_(None))
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
async def test_rate_links_to_originating_roll_event(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A normal roll -> rate flow records the exact originating roll on the rate."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    for position in range(1, 5):
        thread = Thread(
            title=f"Pool Thread {position}",
            format="Comic",
            issues_remaining=5,
            queue_position=position,
            status="active",
            user_id=user.id,
        )
        async_db.add(thread)
    await async_db.commit()

    session, roll_event = await _roll_via_api(auth_client, async_db)

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    rate_event = await _latest_rate_event(async_db, session.id)
    assert rate_event.source_roll_event_id == roll_event.id


@pytest.mark.asyncio
async def test_multiple_rolls_and_rates_each_link_to_their_own_roll(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Repeated rolls and rates in one session link each rate to its own roll."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread_a = await _create_thread(async_db, user.id, "Thread A")
    thread_b = await _create_thread(async_db, user.id, "Thread B")

    roll_a = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread_a.id,
        selection_method="random",
        session_id=session.id,
    )
    async_db.add(roll_a)
    session.pending_thread_id = thread_a.id
    await async_db.commit()

    first_rate = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert first_rate.status_code == 200

    roll_b = Event(
        type="roll",
        die=8,
        result=2,
        selected_thread_id=thread_b.id,
        selection_method="random",
        session_id=session.id,
    )
    async_db.add(roll_b)
    session.pending_thread_id = thread_b.id
    await async_db.commit()

    second_rate = await auth_client.post("/api/rate/", json={"rating": 3.0, "issues_read": 1})
    assert second_rate.status_code == 200

    rate_events = (
        (
            await async_db.execute(
                select(Event)
                .where(Event.session_id == session.id)
                .where(Event.type == "rate")
                .order_by(Event.id.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(rate_events) == 2
    assert rate_events[0].source_roll_event_id == roll_a.id
    assert rate_events[1].source_roll_event_id == roll_b.id


@pytest.mark.asyncio
async def test_rate_does_not_link_to_earlier_roll_for_another_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A stale pending thread with no matching roll keeps NULL linkage."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    rolled_thread = await _create_thread(async_db, user.id, "Rolled Thread")
    pending_thread = await _create_thread(async_db, user.id, "Pending Thread")

    session = SessionModel(start_die=10, user_id=user.id, pending_thread_id=pending_thread.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    stale_roll = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=rolled_thread.id,
        selection_method="random",
        session_id=session.id,
    )
    async_db.add(stale_roll)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    rate_event = await _latest_rate_event(async_db, session.id)
    assert rate_event.thread_id == pending_thread.id
    assert rate_event.source_roll_event_id != stale_roll.id
    assert rate_event.source_roll_event_id is None


@pytest.mark.asyncio
async def test_rate_links_to_latest_matching_roll_not_older_duplicate(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """When the same thread was rolled twice, the newest matching roll wins."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = await _create_thread(async_db, user.id, "Re-rolled Thread")

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    older_roll = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
    )
    newer_roll = Event(
        type="roll",
        die=12,
        result=3,
        selected_thread_id=thread.id,
        selection_method="override",
        session_id=session.id,
    )
    async_db.add_all([older_roll, newer_roll])
    session.pending_thread_id = thread.id
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    rate_event = await _latest_rate_event(async_db, session.id)
    assert rate_event.source_roll_event_id == newer_roll.id


@pytest.mark.asyncio
async def test_override_roll_links_as_originating_selection(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """The manual override roll path links when it is the originating selection."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    override_thread = await _create_thread(async_db, user.id, "Override Thread")
    for position in range(2, 6):
        filler = Thread(
            title=f"Filler {position}",
            format="Comic",
            issues_remaining=5,
            queue_position=position + 20,
            status="active",
            user_id=user.id,
        )
        async_db.add(filler)
    await async_db.commit()

    response = await auth_client.post(
        "/api/roll/override", json={"thread_id": override_thread.id}
    )
    assert response.status_code == 200

    session_result = await async_db.execute(
        select(SessionModel).where(SessionModel.ended_at.is_(None))
    )
    session = session_result.scalars().one()

    override_roll_result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "roll")
        .where(Event.selection_method == "override")
    )
    override_roll = override_roll_result.scalars().one()
    assert override_roll.selected_thread_id == override_thread.id

    rate_response = await auth_client.post(
        "/api/rate/", json={"rating": 4.0, "issues_read": 1}
    )
    assert rate_response.status_code == 200

    rate_event = await _latest_rate_event(async_db, session.id)
    assert rate_event.source_roll_event_id == override_roll.id


@pytest.mark.asyncio
async def test_stale_session_without_matching_roll_keeps_null_linkage(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Malformed sessions with pending but no roll still rate and stay unlinked."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = await _create_thread(async_db, user.id, "Orphan Pending Thread")

    session = SessionModel(start_die=10, user_id=user.id, pending_thread_id=thread.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    rate_event = await _latest_rate_event(async_db, session.id)
    assert rate_event.source_roll_event_id is None


@pytest.mark.asyncio
async def test_fallback_latest_action_roll_links_without_pending_state(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Legacy sessions without pending state link via the latest action roll."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = await _create_thread(async_db, user.id, "Legacy Flow Thread")

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    legacy_roll = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
    )
    async_db.add(legacy_roll)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    rate_event = await _latest_rate_event(async_db, session.id)
    assert rate_event.source_roll_event_id == legacy_roll.id


@pytest.mark.asyncio
async def test_rate_in_second_session_never_links_to_other_session_roll(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Linkage stays within the rating session; foreign-session rolls are ignored."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = await _create_thread(async_db, user.id, "Cross Session Thread")

    old_session = SessionModel(
        start_die=10, user_id=user.id, ended_at=None, pending_thread_id=None
    )
    async_db.add(old_session)
    await async_db.commit()
    await async_db.refresh(old_session)

    foreign_roll = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=old_session.id,
    )
    async_db.add(foreign_roll)
    old_session.ended_at = datetime.now(UTC)
    await async_db.commit()

    current_session = SessionModel(
        start_die=10, user_id=user.id, pending_thread_id=thread.id
    )
    async_db.add(current_session)
    await async_db.commit()
    await async_db.refresh(current_session)

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    rate_event = await _latest_rate_event(async_db, current_session.id)
    assert rate_event.source_roll_event_id is None


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
