"""Session details timeline must degrade gracefully for deleted threads.

Regression coverage for issue #3265: roll events reference their thread via
``selected_thread_id`` with no foreign key, so the event survives thread
deletion while the title lookup misses. The timeline must flag the event
with ``thread_deleted`` and recover the last-known title from snapshots
instead of rendering an error-like "Thread unavailable" state.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, ReadingSession, Snapshot, Thread, User
from app.repositories.undo_snapshot_repository import UndoSnapshotRepository


async def _make_session_and_thread(
    async_db: AsyncSession, default_user: User, title: str = "Saga"
) -> tuple[ReadingSession, Thread]:
    """Create a session and an owned thread, returning both."""
    session = ReadingSession(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)
    return session, thread


@pytest.mark.asyncio
async def test_deleted_thread_roll_recovers_title_from_snapshot(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A roll for a deleted thread shows the snapshot title with a deleted flag."""
    session, thread = await _make_session_and_thread(async_db, default_user)
    thread_id = thread.id

    async_db.add(
        Snapshot(
            session_id=session.id,
            thread_states={str(thread_id): {"title": "Saga", "queue_position": 1}},
            description="Session start",
        )
    )
    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread_id,
            die=20,
            result=20,
            selection_method="random",
            issue_number="1",
        )
    )
    await async_db.commit()

    await async_db.delete(thread)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/sessions/{session.id}/details")
    assert response.status_code == 200
    data = response.json()
    assert len(data["events"]) == 1
    event = data["events"][0]
    assert event["thread_deleted"] is True
    assert event["thread_title"] == "Saga"
    assert event["issue_number"] == "1"
    assert event["description"] == "Selected Saga (deleted)"


@pytest.mark.asyncio
async def test_deleted_thread_roll_without_snapshot_falls_back_gracefully(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Without snapshot coverage the timeline still flags the deletion."""
    session, thread = await _make_session_and_thread(async_db, default_user)
    thread_id = thread.id

    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread_id,
            die=20,
            result=20,
            selection_method="random",
        )
    )
    await async_db.commit()

    await async_db.delete(thread)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/sessions/{session.id}/details")
    assert response.status_code == 200
    data = response.json()
    assert len(data["events"]) == 1
    event = data["events"][0]
    assert event["thread_deleted"] is True
    assert event["thread_title"] is None
    assert event["description"] == "Selected deleted thread"


@pytest.mark.asyncio
async def test_live_thread_roll_is_not_marked_deleted(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Events for live threads keep the default non-deleted shape."""
    session, thread = await _make_session_and_thread(async_db, default_user)

    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread.id,
            die=6,
            result=4,
            selection_method="random",
        )
    )
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/sessions/{session.id}/details")
    assert response.status_code == 200
    data = response.json()
    assert len(data["events"]) == 1
    event = data["events"][0]
    assert event["thread_deleted"] is False
    assert event["thread_title"] == "Saga"
    assert event["description"] == "Selected Saga"


@pytest.mark.asyncio
async def test_undo_of_roll_preserves_selected_thread_reference(
    async_db: AsyncSession, default_user: User
) -> None:
    """Undoing a roll keeps the roll's thread so the card can name it."""
    session, thread = await _make_session_and_thread(async_db, default_user)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(roll_event)
    await async_db.commit()
    await async_db.refresh(roll_event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=roll_event.id,
        thread_states={str(thread.id): {"title": "Saga", "queue_position": 1}},
        session_state={"current_die": 6},
        description="Before roll",
    )
    async_db.add(snapshot)
    await async_db.commit()
    await async_db.refresh(snapshot)

    undo_event = await UndoSnapshotRepository(async_db).create_undo_event(session.id, snapshot)
    await async_db.flush()

    assert undo_event.type == "undo"
    assert undo_event.selected_thread_id == thread.id


@pytest.mark.asyncio
async def test_timeline_resolves_live_thread_for_undo_of_roll(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A restored roll names its live thread instead of flagging it deleted.

    ``create_undo_event`` preserves the roll's ``selected_thread_id``, so the
    details endpoint must resolve that reference with the same rule the
    timeline uses; otherwise a live thread would be reported as deleted
    (#3265).
    """
    session, thread = await _make_session_and_thread(async_db, default_user)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(roll_event)
    await async_db.commit()
    await async_db.refresh(roll_event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=roll_event.id,
        thread_states={str(thread.id): {"title": "Saga", "queue_position": 1}},
        session_state={"current_die": 6},
        description="Before roll",
    )
    async_db.add(snapshot)
    await async_db.commit()
    await async_db.refresh(snapshot)

    await UndoSnapshotRepository(async_db).create_undo_event(session.id, snapshot)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/sessions/{session.id}/details")
    assert response.status_code == 200
    undo_events = [event for event in response.json()["events"] if event["type"] == "undo"]
    assert len(undo_events) == 1
    assert undo_events[0]["thread_title"] == "Saga"
    assert undo_events[0]["thread_deleted"] is False


@pytest.mark.asyncio
async def test_undo_of_rate_carries_issue_number_and_rating(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A real undo copies the rated issue link, number, and rating (#4330)."""
    session, thread = await _make_session_and_thread(async_db, default_user)
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add(issue)
    await async_db.commit()
    await async_db.refresh(issue)

    rate_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        issue_id=issue.id,
        issue_number="1",
    )
    async_db.add(rate_event)
    await async_db.commit()
    await async_db.refresh(rate_event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=rate_event.id,
        thread_states={str(thread.id): {"title": "Saga", "queue_position": 1}},
        session_state={"current_die": 6},
        description="After rating",
    )
    async_db.add(snapshot)
    await async_db.commit()
    await async_db.refresh(snapshot)

    undo_response = await auth_client.post(
        f"/api/v1/undo/{session.id}/undo/{snapshot.id}"
    )
    assert undo_response.status_code == 200

    stored_undo = (
        await async_db.execute(select(Event).where(Event.type == "undo"))
    ).scalar_one()
    assert stored_undo.issue_id == issue.id
    assert stored_undo.issue_number == "1"
    assert stored_undo.rating == 4.5

    response = await auth_client.get(f"/api/v1/sessions/{session.id}/details")
    assert response.status_code == 200
    undo_events = [event for event in response.json()["events"] if event["type"] == "undo"]
    assert len(undo_events) == 1
    assert undo_events[0]["thread_title"] == "Saga"
    assert undo_events[0]["issue_number"] == "1"
    assert undo_events[0]["rating"] == 4.5
