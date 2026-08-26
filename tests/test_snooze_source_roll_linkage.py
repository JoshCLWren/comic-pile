"""Tests linking snooze events to their exact originating roll events."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models import Session as SessionModel


async def _create_session_with_thread(
    async_db: AsyncSession,
    user_id: int,
    *,
    title: str = "Test Thread",
    start_die: int = 6,
    queue_position: int = 1,
) -> tuple[SessionModel, Thread]:
    """Create one active reading session with one active thread."""
    session = SessionModel(start_die=start_die, user_id=user_id)
    async_db.add(session)
    await async_db.flush()

    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=5,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
    )
    async_db.add(thread)
    await async_db.flush()
    return session, thread


async def _add_thread_to_session(
    async_db: AsyncSession,
    session: SessionModel,
    user_id: int,
    *,
    title: str = "Test Thread",
    queue_position: int = 1,
) -> Thread:
    """Add a thread to an existing session."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=5,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


def _add_roll_event(
    async_db: AsyncSession,
    session_id: int,
    thread_id: int,
    selection_method: str = "random",
    die: int = 6,
) -> Event:
    """Append one roll event selecting the given thread, mirroring roll APIs."""
    event = Event(
        type="roll",
        die=die,
        result=1 if selection_method == "random" else 0,
        selected_thread_id=thread_id,
        selection_method=selection_method,
        session_id=session_id,
    )
    async_db.add(event)
    return event


async def _snooze_events_for_session(
    async_db: AsyncSession, session_id: int
) -> list[Event]:
    """Return all snooze events for a session in creation order."""
    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type == "snooze")
        .order_by(Event.id)
    )
    return list(result.scalars().all())


async def _roll_events_by_thread(async_db: AsyncSession) -> dict[int, list[Event]]:
    """Map every roll event ID by its selected thread."""
    result = await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id))
    rolls_by_thread: dict[int, list[Event]] = {}
    for event in result.scalars().all():
        rolls_by_thread.setdefault(event.selected_thread_id or -1, []).append(event)
    return rolls_by_thread


@pytest.mark.asyncio
async def test_snooze_links_to_originating_roll_event(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A normal roll then snooze records the originating roll on the snooze event.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session, thread = await _create_session_with_thread(async_db, user.id)

    roll_event = _add_roll_event(async_db, session.id, thread.id)
    await async_db.refresh(session)
    session.pending_thread_id = thread.id
    await async_db.commit()

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200

    data = response.json()
    assert thread.id in data["snoozed_thread_ids"]
    # Pre-existing snooze side effects are unchanged.
    assert data["current_die"] == 8

    snooze_events = await _snooze_events_for_session(async_db, session.id)
    assert len(snooze_events) == 1
    assert snooze_events[0].source_roll_event_id == roll_event.id
    assert snooze_events[0].thread_id == thread.id
    assert snooze_events[0].die == 6
    assert snooze_events[0].die_after == 8


@pytest.mark.asyncio
async def test_consecutive_cycles_link_each_snooze_to_its_own_roll(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Back-to-back roll/snooze cycles each link to their own roll event.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session, thread_a = await _create_session_with_thread(
        async_db, user.id, title="Thread A", queue_position=1
    )
    thread_b = await _add_thread_to_session(
        async_db, session, user.id, title="Thread B", queue_position=2
    )

    roll_a = _add_roll_event(async_db, session.id, thread_a.id)
    await async_db.refresh(session)
    session.pending_thread_id = thread_a.id
    await async_db.commit()

    first_snooze_response = await auth_client.post("/api/snooze/")
    assert first_snooze_response.status_code == 200

    roll_b = _add_roll_event(async_db, session.id, thread_b.id)
    await async_db.refresh(session)
    session.pending_thread_id = thread_b.id
    await async_db.commit()

    second_snooze_response = await auth_client.post("/api/snooze/")
    assert second_snooze_response.status_code == 200

    snooze_events = await _snooze_events_for_session(async_db, session.id)
    assert len(snooze_events) == 2
    assert snooze_events[0].thread_id == thread_a.id
    assert snooze_events[0].source_roll_event_id == roll_a.id
    assert snooze_events[1].thread_id == thread_b.id
    assert snooze_events[1].source_roll_event_id == roll_b.id


@pytest.mark.asyncio
async def test_repeated_roll_of_same_thread_links_latest_roll(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Re-selecting a previously rolled thread links to the newest roll event.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session, thread = await _create_session_with_thread(async_db, user.id)

    first_roll = _add_roll_event(async_db, session.id, thread.id)
    second_roll = _add_roll_event(async_db, session.id, thread.id)
    await async_db.refresh(session)
    session.pending_thread_id = thread.id
    await async_db.commit()
    assert first_roll.id != second_roll.id

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200

    snooze_events = await _snooze_events_for_session(async_db, session.id)
    assert len(snooze_events) == 1
    assert snooze_events[0].source_roll_event_id == second_roll.id


@pytest.mark.asyncio
async def test_snooze_does_not_link_to_other_threads_roll(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A pending recommendation without its own roll stays unlinked.

    An earlier roll selected another thread in this session, so the snooze must
    record NULL rather than pointing at that unrelated roll event.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session, thread_a = await _create_session_with_thread(
        async_db, user.id, title="Rolled Thread", queue_position=1
    )
    thread_b = await _add_thread_to_session(
        async_db, session, user.id, title="Manually Pending Thread", queue_position=2
    )

    other_roll = _add_roll_event(async_db, session.id, thread_a.id)
    await async_db.refresh(session)
    # Simulate a flow that sets the pending thread without creating a new roll
    # event (for example, set-current-issue).
    session.pending_thread_id = thread_b.id
    await async_db.commit()

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200
    assert thread_b.id in response.json()["snoozed_thread_ids"]

    snooze_events = await _snooze_events_for_session(async_db, session.id)
    assert len(snooze_events) == 1
    assert snooze_events[0].thread_id == thread_b.id
    assert snooze_events[0].source_roll_event_id is None
    assert snooze_events[0].source_roll_event_id != other_roll.id


@pytest.mark.asyncio
@pytest.mark.parametrize("selection_method", ["manual", "override"])
async def test_manual_and_override_pending_rolls_link_to_their_roll_event(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    selection_method: str,
) -> None:
    """Manually or override-originated pending rolls link to their roll event.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
        selection_method: Selection method recorded on the origin roll event.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session, thread = await _create_session_with_thread(async_db, user.id)

    roll_event = _add_roll_event(
        async_db, session.id, thread.id, selection_method=selection_method
    )
    await async_db.refresh(session)
    session.pending_thread_id = thread.id
    await async_db.commit()

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200

    snooze_events = await _snooze_events_for_session(async_db, session.id)
    assert len(snooze_events) == 1
    assert snooze_events[0].source_roll_event_id == roll_event.id


@pytest.mark.asyncio
async def test_snooze_source_roll_survives_later_session_reads(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Linked and unlinked events keep their linkage across reloads.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session, thread = await _create_session_with_thread(async_db, user.id)

    roll_event = _add_roll_event(async_db, session.id, thread.id)
    await async_db.flush()  # Ensure roll_event.id is assigned
    linked_snooze = Event(
        type="snooze",
        session_id=session.id,
        thread_id=thread.id,
        source_roll_event_id=roll_event.id,
    )
    unlinked_snooze = Event(
        type="snooze",
        session_id=session.id,
        thread_id=None,
    )
    async_db.add_all([linked_snooze, unlinked_snooze])
    await async_db.commit()

    reloaded_linked = await async_db.get(Event, linked_snooze.id)
    reloaded_unlinked = await async_db.get(Event, unlinked_snooze.id)
    assert reloaded_linked is not None
    assert reloaded_unlinked is not None
    assert reloaded_linked.source_roll_event_id == roll_event.id
    assert reloaded_unlinked.source_roll_event_id is None


@pytest.mark.asyncio
async def test_event_source_roll_rejects_unknown_reference(
    async_db: AsyncSession,
) -> None:
    """A snooze cannot reference a nonexistent roll event.

    Args:
        async_db: Async database session for direct database queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session, thread = await _create_session_with_thread(async_db, user.id)

    orphan_snooze = Event(
        type="snooze",
        session_id=session.id,
        thread_id=thread.id,
        source_roll_event_id=987654321,
    )
    async_db.add(orphan_snooze)

    with pytest.raises(IntegrityError):
        await async_db.commit()
    await async_db.rollback()


@pytest.mark.asyncio
async def test_deleting_originating_roll_keeps_snooze_and_nulls_link(
    async_db: AsyncSession,
) -> None:
    """Removing an origin roll nullifies the link instead of cascading deletes.

    Args:
        async_db: Async database session for direct database queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session, thread = await _create_session_with_thread(async_db, user.id)

    roll_event = _add_roll_event(async_db, session.id, thread.id)
    snooze_event = Event(
        type="snooze",
        session_id=session.id,
        thread_id=thread.id,
        source_roll_event_id=roll_event.id,
    )
    async_db.add(snooze_event)
    await async_db.commit()

    await async_db.delete(roll_event)
    await async_db.commit()

    surviving_snooze = await async_db.get(Event, snooze_event.id)
    assert surviving_snooze is not None
    rolls_by_thread = await _roll_events_by_thread(async_db)
    assert rolls_by_thread.get(thread.id) in (None, [])
    assert surviving_snooze.source_roll_event_id is None
