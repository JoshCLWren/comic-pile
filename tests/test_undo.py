"""Tests for undo functionality."""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Snapshot, Thread, User
from app.models import Session as SessionModel


@pytest_asyncio.fixture(scope="function")
async def sample_user(async_db: AsyncSession) -> User:
    """Create a test user for undo tests."""
    from tests.conftest import get_or_create_user_async

    return await get_or_create_user_async(async_db)


@pytest.mark.asyncio
async def test_list_snapshots_empty(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test listing snapshots for a session with no snapshots."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.get(f"/api/undo/{session.id}/snapshots")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_snapshots_with_data(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test listing snapshots for a session with snapshots."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=5.0,
        issues_read=1,
        die=6,
        die_after=4,
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 10, "queue_position": 1}},
        description="Test snapshot",
    )
    async_db.add(snapshot)
    await async_db.commit()

    response = await auth_client.get(f"/api/undo/{session.id}/snapshots")
    assert response.status_code == 200
    snapshots = response.json()
    assert len(snapshots) == 1
    assert snapshots[0]["id"] == snapshot.id
    assert snapshots[0]["description"] == "Test snapshot"
    assert snapshots[0]["event_id"] == event.id


@pytest.mark.asyncio
async def test_list_snapshots_invalid_session(auth_client: AsyncClient) -> None:
    """Test listing snapshots for non-existent session."""
    response = await auth_client.get("/api/undo/9999/snapshots")
    assert response.status_code == 404
    assert "Session 9999 not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_undo_to_snapshot(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test undoing to a specific snapshot."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        last_rating=4.0,
        user_id=sample_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

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
    async_db.add(snapshot)
    await async_db.commit()

    response = await auth_client.post(f"/api/undo/{session.id}/undo/{snapshot.id}")
    assert response.status_code == 200

    await async_db.refresh(thread)
    assert thread.issues_remaining == 15
    assert thread.queue_position == 1
    assert thread.last_rating == 5.0
    assert thread.status == "active"


@pytest.mark.asyncio
async def test_undo_to_snapshot_invalid_session(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test undoing with invalid session ID."""
    _ = async_db, sample_user
    response = await auth_client.post("/api/undo/9999/undo/1")
    assert response.status_code == 404
    assert "Session 9999 not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_undo_to_snapshot_invalid_snapshot(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test undoing with invalid snapshot ID."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.post(f"/api/undo/{session.id}/undo/9999")
    assert response.status_code == 404
    assert "Snapshot 9999 not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_undo_to_snapshot_restores_thread_states(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test that undo correctly restores all thread states."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

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
    async_db.add_all([thread1, thread2])
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread1.id,
        selected_thread_id=thread1.id,
        result=3,
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

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
    async_db.add(snapshot)
    await async_db.commit()

    await auth_client.post(f"/api/undo/{session.id}/undo/{snapshot.id}")

    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    assert thread1.issues_remaining == 10
    assert thread1.queue_position == 2
    assert thread1.last_rating == 5.0

    assert thread2.issues_remaining == 20
    assert thread2.queue_position == 1
    assert thread2.last_rating == 4.0


@pytest.mark.asyncio
async def test_snapshot_created_on_rating(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test that a snapshot is automatically created when rating."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    async_db.add(roll_event)
    await async_db.commit()

    response = await auth_client.post(
        "/api/rate/",
        json={"rating": 5.0, "issues_read": 1},
    )
    assert response.status_code == 200

    result = await async_db.execute(
        select(Snapshot).where(Snapshot.session_id == session.id)
    )
    snapshots = result.scalars().all()
    assert len(snapshots) == 1
    assert snapshots[0].description is not None
    assert "After rating" in snapshots[0].description
    assert str(thread.id) in snapshots[0].thread_states


@pytest.mark.asyncio
async def test_multiple_snapshots_listed_in_order(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test that multiple snapshots are listed in reverse chronological order."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

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
        async_db.add(event)
        await async_db.commit()
        await async_db.refresh(event)

        snapshot = Snapshot(
            session_id=session.id,
            event_id=event.id,
            thread_states={thread.id: {"issues_remaining": 10 - i}},
            description=f"Snapshot {i}",
        )
        async_db.add(snapshot)
        await async_db.commit()

    response = await auth_client.get(f"/api/undo/{session.id}/snapshots")
    assert response.status_code == 200
    snapshots = response.json()
    assert len(snapshots) == 3
    assert snapshots[0]["description"] == "Snapshot 2"
    assert snapshots[1]["description"] == "Snapshot 1"
    assert snapshots[2]["description"] == "Snapshot 0"


@pytest.mark.asyncio
async def test_undo_to_earliest_snapshot(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test undoing to earliest snapshot in a session."""
    session = SessionModel(start_die=6, user_id=sample_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    earliest_event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    async_db.add(earliest_event)
    await async_db.commit()
    await async_db.refresh(earliest_event)

    earliest_snapshot = Snapshot(
        session_id=session.id,
        event_id=earliest_event.id,
        thread_states={thread.id: {"issues_remaining": 100}},
        description="Earliest snapshot",
    )
    async_db.add(earliest_snapshot)
    await async_db.commit()

    latest_event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=5,
    )
    async_db.add(latest_event)
    await async_db.commit()

    latest_snapshot = Snapshot(
        session_id=session.id,
        event_id=latest_event.id,
        thread_states={thread.id: {"issues_remaining": 5}},
        description="Latest snapshot",
    )
    async_db.add(latest_snapshot)
    await async_db.commit()

    await auth_client.post(f"/api/undo/{session.id}/undo/{earliest_snapshot.id}")

    await async_db.refresh(thread)
    assert thread.issues_remaining == 100


@pytest.mark.asyncio
async def test_undo_restores_session_state(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test that undo correctly restores session state (start_die, manual_die)."""
    session = SessionModel(
        start_die=6, manual_die=4, user_id=sample_user.id, started_at=datetime.now(UTC)
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 15}},
        session_state={"start_die": 10, "manual_die": 8},
        description="Session with different dice",
    )
    async_db.add(snapshot)
    await async_db.commit()

    response = await auth_client.post(f"/api/undo/{session.id}/undo/{snapshot.id}")
    assert response.status_code == 200

    await async_db.refresh(session)
    assert session.start_die == 10
    assert session.manual_die == 8


@pytest.mark.asyncio
async def test_undo_to_session_start_snapshot(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test undoing to session start snapshot restores initial state."""
    session = SessionModel(start_die=20, user_id=sample_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=5,
        queue_position=1,
        user_id=sample_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    async_db.add(event)
    await async_db.commit()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=None,
        thread_states={thread.id: {"issues_remaining": 10, "queue_position": 1}},
        session_state={"start_die": 6, "manual_die": None},
        description="Session start",
    )
    async_db.add(snapshot)
    await async_db.commit()

    await auth_client.post(f"/api/undo/{session.id}/undo/{snapshot.id}")

    await async_db.refresh(session)
    await async_db.refresh(thread)

    assert session.start_die == 6
    assert session.manual_die is None
    assert thread.issues_remaining == 10
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_undo_handles_missing_session_state(
    auth_client: AsyncClient, async_db: AsyncSession, sample_user: User
) -> None:
    """Test that undo works when snapshot has no session_state (backward compatibility)."""
    session = SessionModel(
        start_die=6, manual_die=4, user_id=sample_user.id, started_at=datetime.now(UTC)
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=sample_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        session_id=session.id,
        thread_id=thread.id,
        selected_thread_id=thread.id,
        result=3,
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 15}},
        session_state=None,
        description="Old snapshot without session state",
    )
    async_db.add(snapshot)
    await async_db.commit()

    original_start_die = session.start_die
    original_manual_die = session.manual_die

    response = await auth_client.post(f"/api/undo/{session.id}/undo/{snapshot.id}")
    assert response.status_code == 200

    await async_db.refresh(session)

    assert session.start_die == original_start_die
    assert session.manual_die == original_manual_die
    assert thread.issues_remaining == 15
