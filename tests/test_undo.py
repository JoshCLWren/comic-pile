"""Tests for undo functionality."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Event, Session as SessionModel, Snapshot, Thread, User  # noqa: I001


@pytest.fixture(scope="function")
def sample_user(db) -> User:
    """Create a test user for undo tests."""
    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=datetime.now(UTC))
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_list_snapshots_empty(client: AsyncClient, db, sample_user):
    """Test listing snapshots for a session with no snapshots."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    response = await client.get(f"/undo/{session.id}/snapshots")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_snapshots_with_data(client: AsyncClient, db, sample_user):
    """Test listing snapshots for a session with snapshots."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=5.0,
        issues_read=1,
        die=6,
        die_after=4,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 10, "queue_position": 1}},
        description="Test snapshot",
    )
    db.add(snapshot)
    db.commit()

    response = await client.get(f"/undo/{session.id}/snapshots")
    assert response.status_code == 200
    snapshots = response.json()
    assert len(snapshots) == 1
    assert snapshots[0]["id"] == snapshot.id
    assert snapshots[0]["description"] == "Test snapshot"
    assert snapshots[0]["event_id"] == event.id


@pytest.mark.asyncio
async def test_list_snapshots_invalid_session(client: AsyncClient):
    """Test listing snapshots for non-existent session."""
    response = await client.get("/undo/9999/snapshots")
    assert response.status_code == 404
    assert "Session 9999 not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_undo_to_snapshot(client: AsyncClient, db, sample_user):
    """Test undoing to a specific snapshot."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        last_rating=4.0,
        user_id=sample_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={
            thread.id: {
                "issues_remaining": 15,
                "queue_position": 1,
                "last_rating": 5.0,
                "status": "active",
                "last_activity_at": datetime.now(UTC).isoformat(),
            }
        },
        description="Before changes",
    )
    db.add(snapshot)
    db.commit()

    response = await client.post(f"/undo/{session.id}/undo/{snapshot.id}")
    assert response.status_code == 200

    db.refresh(thread)
    assert thread.issues_remaining == 15
    assert thread.queue_position == 1
    assert thread.last_rating == 5.0
    assert thread.status == "active"


@pytest.mark.asyncio
async def test_undo_to_snapshot_invalid_session(client: AsyncClient, db, sample_user):
    """Test undoing with invalid session ID."""
    response = await client.post("/undo/9999/undo/1")
    assert response.status_code == 404
    assert "Session 9999 not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_undo_to_snapshot_invalid_snapshot(client: AsyncClient, db, sample_user):
    """Test undoing with invalid snapshot ID."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    response = await client.post(f"/undo/{session.id}/undo/9999")
    assert response.status_code == 404
    assert "Snapshot 9999 not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_undo_to_snapshot_restores_thread_states(client: AsyncClient, db, sample_user):
    """Test that undo correctly restores all thread states."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread1 = Thread(
        title="Comic 1",
        format="comic",
        issues_remaining=5,
        queue_position=1,
        last_rating=4.0,
        user_id=sample_user.id,
    )
    thread2 = Thread(
        title="Comic 2",
        format="trade",
        issues_remaining=15,
        queue_position=2,
        last_rating=3.0,
        user_id=sample_user.id,
    )
    db.add_all([thread1, thread2])
    db.commit()
    db.refresh(thread1)
    db.refresh(thread2)

    event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread1.id,
        selected_thread_id=thread1.id,
        result=3,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={
            thread1.id: {
                "issues_remaining": 10,
                "queue_position": 2,
                "last_rating": 5.0,
                "status": "active",
                "last_activity_at": datetime.now(UTC).isoformat(),
            },
            thread2.id: {
                "issues_remaining": 20,
                "queue_position": 1,
                "last_rating": 4.0,
                "status": "active",
                "last_activity_at": datetime.now(UTC).isoformat(),
            },
        },
        description="Restore both threads",
    )
    db.add(snapshot)
    db.commit()

    await client.post(f"/undo/{session.id}/undo/{snapshot.id}")

    db.refresh(thread1)
    db.refresh(thread2)

    assert thread1.issues_remaining == 10
    assert thread1.queue_position == 2
    assert thread1.last_rating == 5.0

    assert thread2.issues_remaining == 20
    assert thread2.queue_position == 1
    assert thread2.last_rating == 4.0


@pytest.mark.asyncio
async def test_snapshot_created_on_rating(client: AsyncClient, db, sample_user):
    """Test that a snapshot is automatically created when rating."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    db.add(roll_event)
    db.commit()

    response = await client.post(
        "/rate/",
        json={"thread_id": thread.id, "rating": 5.0, "issues_read": 1},
    )
    assert response.status_code == 200

    snapshots = db.query(Snapshot).filter(Snapshot.session_id == session.id).all()
    assert len(snapshots) == 1
    assert "After rating" in snapshots[0].description
    assert str(thread.id) in snapshots[0].thread_states


@pytest.mark.asyncio
async def test_multiple_snapshots_listed_in_order(client: AsyncClient, db, sample_user):
    """Test that multiple snapshots are listed in reverse chronological order."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    for i in range(3):
        event = Event(
            type="rate",
            session_id=session.id,
            thread_id=thread.id,
            rating=4.0,
            issues_read=1,
            die=6,
            die_after=4,
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        snapshot = Snapshot(
            session_id=session.id,
            event_id=event.id,
            thread_states={thread.id: {"issues_remaining": 10 - i}},
            description=f"Snapshot {i}",
        )
        db.add(snapshot)
        db.commit()

    response = await client.get(f"/undo/{session.id}/snapshots")
    assert response.status_code == 200
    snapshots = response.json()
    assert len(snapshots) == 3
    assert snapshots[0]["description"] == "Snapshot 2"
    assert snapshots[1]["description"] == "Snapshot 1"
    assert snapshots[2]["description"] == "Snapshot 0"


@pytest.mark.asyncio
async def test_undo_to_earliest_snapshot(client: AsyncClient, db, sample_user):
    """Test undoing to earliest snapshot in a session."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    earliest_event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    db.add(earliest_event)
    db.commit()
    db.refresh(earliest_event)

    earliest_snapshot = Snapshot(
        session_id=session.id,
        event_id=earliest_event.id,
        thread_states={thread.id: {"issues_remaining": 100}},
        description="Earliest snapshot",
    )
    db.add(earliest_snapshot)
    db.commit()

    latest_event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=5,
    )
    db.add(latest_event)
    db.commit()

    latest_snapshot = Snapshot(
        session_id=session.id,
        event_id=latest_event.id,
        thread_states={thread.id: {"issues_remaining": 5}},
        description="Latest snapshot",
    )
    db.add(latest_snapshot)
    db.commit()

    await client.post(f"/undo/{session.id}/undo/{earliest_snapshot.id}")

    db.refresh(thread)
    assert thread.issues_remaining == 100


@pytest.mark.asyncio
async def test_undo_restores_session_state(client: AsyncClient, db, sample_user):
    """Test that undo correctly restores session state (start_die, manual_die)."""
    session = SessionModel(
        start_die=6, manual_die=4, user_id=sample_user.id, started_at=datetime.now(UTC)
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 15}},
        session_state={"start_die": 10, "manual_die": 8},
        description="Session with different dice",
    )
    db.add(snapshot)
    db.commit()

    response = await client.post(f"/undo/{session.id}/undo/{snapshot.id}")
    assert response.status_code == 200

    db.refresh(session)
    assert session.start_die == 10
    assert session.manual_die == 8


@pytest.mark.asyncio
async def test_undo_to_session_start_snapshot(client: AsyncClient, db, sample_user):
    """Test undoing to session start snapshot restores initial state."""
    session = SessionModel(start_die=20, user_id=sample_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=5,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    db.add(event)
    db.commit()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=None,
        thread_states={thread.id: {"issues_remaining": 10, "queue_position": 1}},
        session_state={"start_die": 6, "manual_die": None},
        description="Session start",
    )
    db.add(snapshot)
    db.commit()

    await client.post(f"/undo/{session.id}/undo/{snapshot.id}")

    db.refresh(session)
    db.refresh(thread)

    assert session.start_die == 6
    assert session.manual_die is None
    assert thread.issues_remaining == 10
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_undo_handles_missing_session_state(client: AsyncClient, db, sample_user):
    """Test that undo works when snapshot has no session_state (backward compatibility)."""
    session = SessionModel(
        start_die=6, manual_die=4, user_id=sample_user.id, started_at=datetime.now(UTC)
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 15}},
        session_state=None,
        description="Old snapshot without session state",
    )
    db.add(snapshot)
    db.commit()

    original_start_die = session.start_die
    original_manual_die = session.manual_die

    response = await client.post(f"/undo/{session.id}/undo/{snapshot.id}")
    assert response.status_code == 200

    db.refresh(session)

    assert session.start_die == original_start_die
    assert session.manual_die == original_manual_die
    assert thread.issues_remaining == 15
