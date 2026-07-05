"""Integration tests for session and history operations."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Snapshot, Thread, User
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_session_lifecycle_creates_history_events(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that full session lifecycle creates proper history events."""
    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

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

    rate_response = await auth_client.post(
        "/api/rate/",
        json={"rating": 5.0, "issues_read": 1},
    )
    assert rate_response.status_code == 200

    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id).order_by(Event.timestamp)
    )
    events = result.scalars().all()

    event_types = [e.type for e in events]
    assert "roll" in event_types
    assert "rate" in event_types


@pytest.mark.asyncio
async def test_undo_operation_creates_history_event(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that undo operation creates a history event."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=15,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 15, "queue_position": 1}},
        description="Before changes",
    )
    async_db.add(snapshot)
    await async_db.commit()

    initial_events_result = await async_db.execute(
        select(Event).where(Event.session_id == session.id)
    )
    initial_events = initial_events_result.scalars().all()

    response = await auth_client.post(f"/api/undo/{session.id}/undo/{snapshot.id}")
    assert response.status_code == 200

    final_events_result = await async_db.execute(
        select(Event).where(Event.session_id == session.id)
    )
    final_events = final_events_result.scalars().all()

    assert len(final_events) >= len(initial_events)


@pytest.mark.asyncio
async def test_session_restore_preserves_events(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that session restore preserves session events."""
    from comic_pile.session import create_session_start_snapshot

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    await create_session_start_snapshot(async_db, session)

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

    rate_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    async_db.add(rate_event)
    await async_db.commit()

    initial_events_result = await async_db.execute(
        select(Event).where(Event.session_id == session.id)
    )
    initial_events = initial_events_result.scalars().all()

    response = await auth_client.post(f"/api/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200

    final_events_result = await async_db.execute(
        select(Event).where(Event.session_id == session.id)
    )
    final_events = final_events_result.scalars().all()

    assert len(final_events) == len(initial_events)


@pytest.mark.asyncio
async def test_multiple_undos_in_sequence(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that multiple undo operations work correctly in sequence."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event1 = Event(type="rate", session_id=session.id, thread_id=thread.id, rating=4.0)
    async_db.add(event1)
    await async_db.commit()

    snapshot1 = Snapshot(
        session_id=session.id,
        event_id=event1.id,
        thread_states={thread.id: {"issues_remaining": 8}},
        description="Snapshot 1",
    )
    async_db.add(snapshot1)
    await async_db.commit()

    thread.issues_remaining = 6
    await async_db.commit()

    event2 = Event(type="rate", session_id=session.id, thread_id=thread.id, rating=5.0)
    async_db.add(event2)
    await async_db.commit()

    snapshot2 = Snapshot(
        session_id=session.id,
        event_id=event2.id,
        thread_states={thread.id: {"issues_remaining": 6}},
        description="Snapshot 2",
    )
    async_db.add(snapshot2)
    await async_db.commit()

    thread.issues_remaining = 4
    await async_db.commit()

    await auth_client.post(f"/api/undo/{session.id}/undo/{snapshot2.id}")
    await async_db.refresh(thread)
    assert thread.issues_remaining == 6

    await auth_client.post(f"/api/undo/{session.id}/undo/{snapshot1.id}")
    await async_db.refresh(thread)
    assert thread.issues_remaining == 8


@pytest.mark.asyncio
async def test_get_session_details_endpoint(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test getting session details with all events."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(roll_event)

    rate_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    async_db.add(rate_event)
    await async_db.commit()

    response = await auth_client.get(f"/api/sessions/{session.id}/details")
    assert response.status_code == 200
    data = response.json()
    event_types = [e["type"] for e in data["events"]]
    assert "roll" in event_types
    assert "rate" in event_types
    assert any(e.get("thread_title") == "Test Comic" for e in data["events"])


@pytest.mark.asyncio
async def test_get_session_snapshots_endpoint(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test getting session snapshots list."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    event = Event(type="rate", session_id=session.id, thread_id=thread.id, rating=4.0)
    async_db.add(event)
    await async_db.commit()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 10}},
        description="Test snapshot",
    )
    async_db.add(snapshot)
    await async_db.commit()

    response = await auth_client.get(f"/api/sessions/{session.id}/snapshots")
    assert response.status_code == 200
    data = response.json()
    assert any(s["description"] == "Test snapshot" for s in data["snapshots"])


@pytest.mark.asyncio
async def test_rating_creates_snapshot_automatically(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that rating operation automatically creates a snapshot."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

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

    initial_snapshots_result = await async_db.execute(
        select(Snapshot).where(Snapshot.session_id == session.id)
    )
    initial_snapshots = initial_snapshots_result.scalars().all()

    response = await auth_client.post(
        "/api/rate/",
        json={"rating": 5.0, "issues_read": 1},
    )
    assert response.status_code == 200

    final_snapshots_result = await async_db.execute(
        select(Snapshot).where(Snapshot.session_id == session.id)
    )
    final_snapshots = final_snapshots_result.scalars().all()

    assert len(final_snapshots) > len(initial_snapshots)
    assert any(
        s.description is not None and "After rating" in s.description
        for s in final_snapshots
    )


@pytest.mark.asyncio
async def test_session_response_includes_restore_point_info(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that session response includes restore point information."""
    from comic_pile.session import create_session_start_snapshot

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    await create_session_start_snapshot(async_db, session)

    response = await auth_client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert "snapshot_count" in data
    assert "has_restore_point" in data
    assert data["has_restore_point"] is True
    assert data["snapshot_count"] >= 1


@pytest.mark.asyncio
async def test_multiple_sessions_listed_in_reverse_order(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that sessions are listed in reverse chronological order."""
    for i in range(5):
        session = SessionModel(
            start_die=6 + i, user_id=default_user.id, started_at=datetime.now(UTC)
        )
        async_db.add(session)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    sessions = response.json()["sessions"]

    session_ids = [s["id"] for s in sessions]
    assert session_ids == sorted(session_ids, reverse=True)


@pytest.mark.asyncio
async def test_undo_to_snapshot_with_session_state(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test undo operation properly restores session state."""
    session = SessionModel(
        start_die=10, manual_die=8, user_id=default_user.id, started_at=datetime.now(UTC)
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=10,
        result=6,
        selection_method="random",
    )
    async_db.add(event)
    await async_db.commit()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 15}},
        session_state={"start_die": 6, "manual_die": 4},
        description="Different session state",
    )
    async_db.add(snapshot)
    await async_db.commit()

    response = await auth_client.post(f"/api/undo/{session.id}/undo/{snapshot.id}")
    assert response.status_code == 200
    data = response.json()

    await async_db.refresh(session)
    assert session.start_die == 6
    assert session.manual_die == 4
    assert data["start_die"] == 6
    assert data["manual_die"] == 4


@pytest.mark.asyncio
async def test_current_session_response_includes_ladder_path(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test current session response includes dice ladder path."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(roll_event)

    rate_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    async_db.add(rate_event)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "ladder_path" in data
    assert "6 → 8" in data["ladder_path"]
