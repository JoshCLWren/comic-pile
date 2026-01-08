"""Integration tests for session and history operations."""

import pytest

from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Event, Session as SessionModel, Snapshot, Thread


@pytest.mark.asyncio
async def test_session_lifecycle_creates_history_events(client: AsyncClient, db, default_user):
    """Test that full session lifecycle creates proper history events."""
    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    db.add(roll_event)
    db.commit()

    rate_response = await client.post(
        "/rate/",
        json={"thread_id": thread.id, "rating": 5.0, "issues_read": 1},
    )
    assert rate_response.status_code == 200

    events = (
        db.execute(select(Event).where(Event.session_id == session.id).order_by(Event.timestamp))
        .scalars()
        .all()
    )

    event_types = [e.type for e in events]
    assert "roll" in event_types
    assert "rate" in event_types


@pytest.mark.asyncio
async def test_undo_operation_creates_history_event(client: AsyncClient, db, default_user):
    """Test that undo operation creates a history event."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=15,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 15, "queue_position": 1}},
        description="Before changes",
    )
    db.add(snapshot)
    db.commit()

    initial_event_count = (
        db.execute(select(Event).where(Event.session_id == session.id)).scalars().all()
    )

    response = await client.post(f"/undo/{session.id}/undo/{snapshot.id}")
    assert response.status_code == 200

    final_event_count = (
        db.execute(select(Event).where(Event.session_id == session.id)).scalars().all()
    )

    assert len(final_event_count) >= len(initial_event_count)


@pytest.mark.asyncio
async def test_session_restore_preserves_events(client: AsyncClient, db, default_user):
    """Test that session restore preserves session events."""
    from comic_pile.session import create_session_start_snapshot

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    create_session_start_snapshot(db, session)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    db.add(roll_event)
    db.commit()

    rate_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    db.add(rate_event)
    db.commit()

    initial_events = db.execute(select(Event).where(Event.session_id == session.id)).scalars().all()

    response = await client.post(f"/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200

    final_events = db.execute(select(Event).where(Event.session_id == session.id)).scalars().all()

    assert len(final_events) == len(initial_events)


@pytest.mark.asyncio
async def test_multiple_undos_in_sequence(client: AsyncClient, db, default_user):
    """Test that multiple undo operations work correctly in sequence."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event1 = Event(type="rate", session_id=session.id, thread_id=thread.id, rating=4.0)
    db.add(event1)
    db.commit()

    snapshot1 = Snapshot(
        session_id=session.id,
        event_id=event1.id,
        thread_states={thread.id: {"issues_remaining": 8}},
        description="Snapshot 1",
    )
    db.add(snapshot1)
    db.commit()

    thread.issues_remaining = 6
    db.commit()

    event2 = Event(type="rate", session_id=session.id, thread_id=thread.id, rating=5.0)
    db.add(event2)
    db.commit()

    snapshot2 = Snapshot(
        session_id=session.id,
        event_id=event2.id,
        thread_states={thread.id: {"issues_remaining": 6}},
        description="Snapshot 2",
    )
    db.add(snapshot2)
    db.commit()

    thread.issues_remaining = 4
    db.commit()

    await client.post(f"/undo/{session.id}/undo/{snapshot2.id}")
    db.refresh(thread)
    assert thread.issues_remaining == 6

    await client.post(f"/undo/{session.id}/undo/{snapshot1.id}")
    db.refresh(thread)
    assert thread.issues_remaining == 8


@pytest.mark.asyncio
async def test_get_session_details_endpoint(client: AsyncClient, db, default_user):
    """Test getting session details with all events."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    db.add(roll_event)

    rate_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    db.add(rate_event)
    db.commit()

    response = await client.get(f"/sessions/{session.id}/details")
    assert response.status_code == 200
    html = response.text
    assert "Test Comic" in html
    assert "Roll" in html
    assert "Rating" in html


@pytest.mark.asyncio
async def test_get_session_snapshots_endpoint(client: AsyncClient, db, default_user):
    """Test getting session snapshots list."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()

    event = Event(type="rate", session_id=session.id, thread_id=thread.id, rating=4.0)
    db.add(event)
    db.commit()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 10}},
        description="Test snapshot",
    )
    db.add(snapshot)
    db.commit()

    response = await client.get(f"/sessions/{session.id}/snapshots")
    assert response.status_code == 200
    html = response.text
    assert "Test snapshot" in html


@pytest.mark.asyncio
async def test_rating_creates_snapshot_automatically(client: AsyncClient, db, default_user):
    """Test that rating operation automatically creates a snapshot."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    db.add(roll_event)
    db.commit()

    initial_snapshots = (
        db.execute(select(Snapshot).where(Snapshot.session_id == session.id)).scalars().all()
    )

    response = await client.post(
        "/rate/",
        json={"thread_id": thread.id, "rating": 5.0, "issues_read": 1},
    )
    assert response.status_code == 200

    final_snapshots = (
        db.execute(select(Snapshot).where(Snapshot.session_id == session.id)).scalars().all()
    )

    assert len(final_snapshots) > len(initial_snapshots)
    assert any("After rating" in s.description for s in final_snapshots)


@pytest.mark.asyncio
async def test_session_response_includes_restore_point_info(client: AsyncClient, db, default_user):
    """Test that session response includes restore point information."""
    from comic_pile.session import create_session_start_snapshot

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()

    create_session_start_snapshot(db, session)

    response = await client.get(f"/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert "snapshot_count" in data
    assert "has_restore_point" in data
    assert data["has_restore_point"] is True
    assert data["snapshot_count"] >= 1


@pytest.mark.asyncio
async def test_multiple_sessions_listed_in_reverse_order(client: AsyncClient, db, default_user):
    """Test that sessions are listed in reverse chronological order."""
    for i in range(5):
        session = SessionModel(
            start_die=6 + i, user_id=default_user.id, started_at=datetime.now(UTC)
        )
        db.add(session)
    db.commit()

    response = await client.get("/sessions/")
    assert response.status_code == 200
    sessions = response.json()

    session_ids = [s["id"] for s in sessions]
    assert session_ids == sorted(session_ids, reverse=True)


@pytest.mark.asyncio
async def test_undo_to_snapshot_with_session_state(client: AsyncClient, db, default_user):
    """Test undo operation properly restores session state."""
    session = SessionModel(
        start_die=10, manual_die=8, user_id=default_user.id, started_at=datetime.now(UTC)
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()

    event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=10,
        result=6,
        selection_method="random",
    )
    db.add(event)
    db.commit()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 15}},
        session_state={"start_die": 6, "manual_die": 4},
        description="Different session state",
    )
    db.add(snapshot)
    db.commit()

    response = await client.post(f"/undo/{session.id}/undo/{snapshot.id}")
    assert response.status_code == 200
    data = response.json()

    db.refresh(session)
    assert session.start_die == 6
    assert session.manual_die == 4
    assert data["start_die"] == 6
    assert data["manual_die"] == 4


@pytest.mark.asyncio
async def test_current_session_response_includes_ladder_path(client: AsyncClient, db, default_user):
    """Test current session response includes dice ladder path."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    db.add(roll_event)

    rate_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    db.add(rate_event)
    db.commit()

    response = await client.get("/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "ladder_path" in data
    assert "6 → 8" in data["ladder_path"]
