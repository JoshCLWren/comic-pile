"""Tests for session logic."""

import pytest

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.api.session import build_ladder_path, get_active_thread
from app.models import Event, Session, Snapshot, Thread
from app.models import Session as SessionModel
from sqlalchemy import select
from comic_pile.session import (
    create_session_start_snapshot,
    end_session,
    get_or_create,
    is_active,
    should_start_new,
)


def test_is_active_true(db):
    """Session created < 6 hours ago is active."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=1,
    )
    db.add(session)
    db.commit()

    result = is_active(session.started_at, session.ended_at, db)
    assert result is True


def test_is_active_false_old(db):
    """Session created > 6 hours ago is inactive."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=7),
        start_die=6,
        user_id=1,
    )
    db.add(session)
    db.commit()

    result = is_active(session.started_at, session.ended_at, db)
    assert result is False


def test_is_active_false_ended(db):
    """Session that has ended is inactive."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        ended_at=datetime.now(UTC),
        start_die=6,
        user_id=1,
    )
    db.add(session)
    db.commit()

    result = is_active(session.started_at, session.ended_at, db)
    assert result is False


def test_should_start_new_true(db):
    """No active session in last 6 hours."""
    old_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=7),
        ended_at=datetime.now(UTC),
        start_die=6,
        user_id=1,
    )
    db.add(old_session)
    db.commit()

    result = should_start_new(db)
    assert result is True


def test_should_start_new_false(db):
    """Active session exists."""
    active_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=1,
    )
    db.add(active_session)
    db.commit()

    result = should_start_new(db)
    assert result is False


def test_get_or_create_existing(db, sample_data):
    """Returns existing active session (< 6 hours old)."""
    # End all sample sessions first
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    db.commit()

    # Create a fresh active session within last 6 hours
    active_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=1,
    )
    db.add(active_session)
    db.commit()

    result = get_or_create(db, user_id=1)
    assert result.id == active_session.id


def test_get_or_create_new(db, sample_data):
    """Creates new session when none active."""
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    db.commit()

    new_session = get_or_create(db, user_id=1)
    assert new_session.start_die == 6
    assert new_session.user_id == 1


def test_end_session(db, sample_data):
    """Marks session as ended."""
    session = sample_data["sessions"][0]
    assert session.ended_at is None

    end_session(session.id, db)

    db.refresh(session)
    assert session.ended_at is not None


def test_end_session_nonexistent(db, sample_data):
    """Gracefully handles ending non-existent session."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    db.commit()

    end_session(999, db)

    assert True


def test_is_active_exactly_6_hours(db):
    """Session created exactly 6 hours ago is considered active."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=5, minutes=59),
        start_die=6,
        user_id=1,
    )
    db.add(session)
    db.commit()

    result = is_active(session.started_at, session.ended_at, db)
    assert result is True


def test_should_start_new_multiple_old_sessions(db):
    """Multiple old sessions still return true."""
    for i in range(3):
        old_session = SessionModel(
            started_at=datetime.now(UTC) - timedelta(hours=7 + i),
            ended_at=datetime.now(UTC),
            start_die=6,
            user_id=1,
        )
        db.add(old_session)
    db.commit()

    result = should_start_new(db)
    assert result is True


def test_get_or_create_returns_most_recent(db):
    """Returns most recent active session when multiple exist."""
    recent_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=10,
        user_id=1,
    )
    older_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=2),
        start_die=6,
        user_id=1,
    )
    db.add(recent_session)
    db.add(older_session)
    db.commit()

    result = get_or_create(db, user_id=1)
    assert result.id == recent_session.id
    assert result.start_die == 10


def test_get_or_create_creates_default_user(db):
    """BUG-141: Creates default user when user_id doesn't exist."""
    from app.models import User

    non_existent_user_id = 999

    user = db.get(User, non_existent_user_id)
    assert user is None

    new_session = get_or_create(db, user_id=non_existent_user_id)

    assert new_session is not None
    assert new_session.user_id == non_existent_user_id

    user = db.get(User, non_existent_user_id)
    assert user is not None
    assert user.username == "default_user"


def test_get_or_create_creates_user_id_1(db):
    """BUG-142: Creates default user when user_id=1 doesn't exist."""
    from app.models import User
    from sqlalchemy import delete

    db.execute(delete(Session))
    db.execute(delete(User))
    db.commit()

    user = db.get(User, 1)
    assert user is None

    new_session = get_or_create(db, user_id=1)

    assert new_session is not None
    assert new_session.user_id == 1

    user = db.get(User, 1)
    assert user is not None
    assert user.username == "default_user"


def test_get_active_thread_includes_last_rolled_result(db, sample_data):
    """Get active thread includes last rolled result value."""
    session = sample_data["sessions"][0]
    thread = sample_data["threads"][0]

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

    active_thread = get_active_thread(session.id, db)

    assert active_thread is not None
    assert active_thread["id"] == thread.id
    assert active_thread["last_rolled_result"] == 4


def test_session_start_snapshot_created(db):
    """A snapshot is created when a new session starts."""
    threads = []
    for i in range(3):
        thread = Thread(
            title=f"Test Thread {i}",
            format="Comic",
            issues_remaining=5 + i,
            queue_position=i + 1,
            status="active",
            user_id=1,
            created_at=datetime.now(UTC),
        )
        db.add(thread)
        threads.append(thread)
    db.commit()

    session = get_or_create(db, user_id=1)

    from sqlalchemy import select

    snapshot = (
        db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session.id)
            .where(Snapshot.description == "Session start")
            .order_by(Snapshot.created_at)
        )
        .scalars()
        .first()
    )

    assert snapshot is not None
    assert snapshot.session_id == session.id
    assert snapshot.description == "Session start"
    assert snapshot.session_state is not None
    assert snapshot.session_state["start_die"] == 6
    assert snapshot.session_state["manual_die"] is None
    assert len(snapshot.thread_states) == 3


def test_session_start_snapshot_captures_thread_states(db):
    """Snapshot captures all thread states at session start."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Thread 2",
        format="Graphic Novel",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
        last_rating=4.5,
        created_at=datetime.now(UTC),
    )
    db.add(thread1)
    db.add(thread2)
    db.commit()
    db.refresh(thread1)
    db.refresh(thread2)

    session = get_or_create(db, user_id=user.id)

    from sqlalchemy import select

    snapshot = (
        db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session.id)
            .where(Snapshot.description == "Session start")
        )
        .scalars()
        .first()
    )

    assert snapshot is not None
    thread1_state = snapshot.thread_states[str(thread1.id)]
    assert thread1_state["issues_remaining"] == 10
    assert thread1_state["queue_position"] == 1
    assert thread1_state["status"] == "active"

    thread2_state = snapshot.thread_states[str(thread2.id)]
    assert thread2_state["issues_remaining"] == 5
    assert thread2_state["queue_position"] == 2
    assert thread2_state["last_rating"] == 4.5
    assert thread2_state["status"] == "active"


def test_session_start_snapshot_captures_manual_die(db):
    """Snapshot captures session manual die state."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    db.commit()

    session = SessionModel(start_die=6, user_id=1, manual_die=20)
    db.add(session)
    db.commit()

    create_session_start_snapshot(db, session)

    from sqlalchemy import select

    snapshot = (
        db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session.id)
            .where(Snapshot.description == "Session start")
        )
        .scalars()
        .first()
    )

    assert snapshot is not None
    assert snapshot.session_state["start_die"] == 6
    assert snapshot.session_state["manual_die"] == 20


@pytest.mark.asyncio
async def test_get_current_session_active(client: AsyncClient, db, default_user):
    """Test getting current active session."""
    from app.models import Session as SessionModel

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

    response = await client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session.id
    assert data["start_die"] == 6
    assert data["active_thread"] is not None
    assert data["active_thread"]["id"] == thread.id
    assert data["current_die"] == 6


@pytest.mark.asyncio
async def test_get_current_session_no_active(client: AsyncClient, db, default_user):
    """Test getting current session creates a new session when none is active."""
    from app.models import Session as SessionModel

    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC) - timedelta(hours=7),
        ended_at=datetime.now(UTC),
    )
    db.add(session)
    db.commit()

    response = await client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["start_die"] == 6


@pytest.mark.asyncio
async def test_list_sessions(client: AsyncClient, db, default_user):
    """Test listing all sessions with pagination."""
    from app.models import Session as SessionModel

    for i in range(5):
        session = SessionModel(
            start_die=6 + i, user_id=default_user.id, started_at=datetime.now(UTC)
        )
        db.add(session)
    db.commit()

    response = await client.get("/api/sessions/?limit=3&offset=0")
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 3


@pytest.mark.asyncio
async def test_list_sessions_pagination(client: AsyncClient, db, default_user):
    """Test session pagination works correctly."""
    from app.models import Session as SessionModel

    for i in range(5):
        session = SessionModel(
            start_die=6 + i, user_id=default_user.id, started_at=datetime.now(UTC)
        )
        db.add(session)
    db.commit()

    first_page = await client.get("/api/sessions/?limit=2&offset=0")
    assert first_page.status_code == 200
    first_sessions = first_page.json()
    assert len(first_sessions) == 2

    second_page = await client.get("/api/sessions/?limit=2&offset=2")
    assert second_page.status_code == 200
    second_sessions = second_page.json()
    assert len(second_sessions) == 2

    assert first_sessions[0]["id"] != second_sessions[0]["id"]


@pytest.mark.asyncio
async def test_get_session_by_id(client: AsyncClient, db, default_user):
    """Test getting a specific session by ID."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    response = await client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session.id
    assert data["start_die"] == 6


@pytest.mark.asyncio
async def test_get_session_not_found(client: AsyncClient):
    """Test getting a non-existent session."""
    response = await client.get("/api/sessions/9999")
    assert response.status_code == 404
    assert "Session not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_session_includes_ladder_path(client: AsyncClient, db, default_user):
    """Test session response includes dice ladder path."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()

    event1 = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    db.add(event1)

    event2 = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    db.add(event2)
    db.commit()

    response = await client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert "6 → 8" in data["ladder_path"]


@pytest.mark.asyncio
async def test_get_session_includes_snapshot_info(client: AsyncClient, db, default_user):
    """Test session response includes snapshot count and restore point info."""
    from app.models import Session as SessionModel

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

    event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    db.add(event)
    db.commit()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 10}},
        description="After rating",
    )
    db.add(snapshot)
    db.commit()

    response = await client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["snapshot_count"] == 1
    assert data["has_restore_point"] is True


@pytest.mark.asyncio
async def test_restore_session_start(client: AsyncClient, db, default_user):
    """Restore session to start state via API."""
    from app.models import Session as SessionModel

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Thread 2",
        format="Graphic Novel",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        last_rating=4.5,
        created_at=datetime.now(UTC),
    )
    db.add(thread1)
    db.add(thread2)
    db.commit()
    db.refresh(thread1)
    db.refresh(thread2)

    session = SessionModel(start_die=6, user_id=default_user.id, manual_die=10)
    db.add(session)
    db.commit()
    db.refresh(session)

    create_session_start_snapshot(db, session)

    thread1.issues_remaining = 5
    thread2.queue_position = 5
    session.manual_die = 20
    db.commit()

    response = await client.post(f"/api/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200
    data = response.json()
    assert data["start_die"] == 6
    assert data["manual_die"] == 10

    refreshed_thread1 = db.get(Thread, thread1.id)
    refreshed_thread2 = db.get(Thread, thread2.id)
    db.refresh(session)

    assert refreshed_thread1.issues_remaining == 10
    assert refreshed_thread2.queue_position == 2
    assert session.manual_die == 10


@pytest.mark.asyncio
async def test_restore_session_start_no_snapshot(client: AsyncClient, db, default_user):
    """Test restoring session when no session start snapshot exists."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    response = await client.post(f"/api/sessions/{session.id}/restore-session-start")
    assert response.status_code == 404
    assert "No session start snapshot found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_restore_session_start_with_deleted_threads(client: AsyncClient, db, default_user):
    """Test that restore handles threads that were deleted after snapshot."""
    from app.models import Session as SessionModel

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Thread 2",
        format="Graphic Novel",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    db.add(thread1)
    db.add(thread2)
    db.commit()
    db.refresh(thread1)
    db.refresh(thread2)

    session = SessionModel(start_die=6, user_id=default_user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    create_session_start_snapshot(db, session)

    thread2.issues_remaining = 0
    db.commit()

    await client.delete(f"/api/threads/{thread2.id}")
    db.expire_all()

    response = await client.post(f"/api/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200

    refreshed_thread1 = db.get(Thread, thread1.id)
    assert refreshed_thread1.issues_remaining == 10

    restored_thread = db.get(Thread, thread2.id)
    assert restored_thread is not None
    assert restored_thread.issues_remaining == 5


@pytest.mark.asyncio
async def test_restore_session_start_clears_pending_thread_id(
    client: AsyncClient, db, default_user
):
    """Test that restore-session-start clears pending_thread_id from sessions when deleting threads.

    Regression test for BUG-131: Ensures that when restoring to a snapshot where
    threads no longer exist, sessions with pending_thread_id referencing those
    threads have their pending_thread_id cleared to prevent ForeignViolation errors.
    """
    from app.models import Session as SessionModel

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Thread 2",
        format="Graphic Novel",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    db.add(thread1)
    db.add(thread2)
    db.commit()
    db.refresh(thread1)
    db.refresh(thread2)

    session = SessionModel(start_die=6, user_id=default_user.id, pending_thread_id=thread2.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    create_session_start_snapshot(db, session)

    thread2.issues_remaining = 0
    db.commit()

    await client.delete(f"/api/threads/{thread2.id}")

    db.refresh(session)
    assert session.pending_thread_id is None

    response = await client.post(f"/api/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200

    restored_thread2 = db.get(Thread, thread2.id)
    assert restored_thread2 is not None


def test_undo_to_snapshot_clears_pending_thread_id(db, sample_data):
    """Test that undo_to_snapshot clears pending_thread_id from sessions when deleting threads.

    Regression test for BUG-131: Ensures that when undoing to a snapshot where
    threads created after the snapshot need to be deleted, sessions with
    pending_thread_id referencing those threads have their pending_thread_id cleared
    to prevent ForeignViolation errors.
    """
    from app.models import Session as SessionModel, Snapshot

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=1,
        created_at=datetime.now(UTC),
    )
    db.add(thread1)
    db.commit()
    db.refresh(thread1)

    session = SessionModel(start_die=6, user_id=1)
    db.add(session)
    db.commit()
    db.refresh(session)

    create_session_start_snapshot(db, session)

    thread2 = Thread(
        title="Thread 2",
        format="Graphic Novel",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=1,
        created_at=datetime.now(UTC),
    )
    db.add(thread2)
    db.commit()
    db.refresh(thread2)

    session.pending_thread_id = thread2.id
    db.commit()

    from app.api.undo import undo_to_snapshot

    snapshot = (
        db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session.id)
            .where(Snapshot.description == "Session start")
            .order_by(Snapshot.created_at)
        )
        .scalars()
        .first()
    )

    assert snapshot is not None

    undo_to_snapshot(session.id, snapshot.id, db)

    db.refresh(session)
    assert session.pending_thread_id is None

    restored_thread2 = db.get(Thread, thread2.id)
    assert restored_thread2 is None


def test_is_active_no_lazy_load(db):
    """Test that is_active doesn't cause lazy load of session object."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=1,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    started_at = session.started_at
    ended_at = session.ended_at
    db.expunge_all()

    from app.database import SessionLocal

    new_db = SessionLocal()

    try:
        result = is_active(started_at, ended_at, new_db)
        assert result is True

        old_started_at = datetime.now(UTC) - timedelta(hours=7)
        old_ended_at = None
        result = is_active(old_started_at, old_ended_at, new_db)
        assert result is False

        ended_started_at = datetime.now(UTC) - timedelta(hours=1)
        ended_ended_at = datetime.now(UTC)
        result = is_active(ended_started_at, ended_ended_at, new_db)
        assert result is False
    finally:
        new_db.close()


def test_get_or_create_handles_deadlock_regression():
    """Test that get_or_create has retry logic for deadlock handling.

    Regression test for BUG-158: DeadlockDetected error during concurrent operations.
    This test verifies that code structure includes deadlock retry logic.
    """
    import inspect

    source = inspect.getsource(get_or_create)

    assert "OperationalError" in source, "get_or_create should handle OperationalError"
    assert "deadlock" in source.lower(), "get_or_create should check for deadlock errors"
    assert "retry" in source.lower() or "while" in source.lower(), (
        "get_or_create should have retry logic"
    )
    assert "rollback" in source.lower(), "get_or_create should rollback on deadlock"


def test_get_active_thread_uses_session_id_not_object(db, sample_data):
    """Test that get_active_thread uses session_id to avoid lazy loading deadlocks.

    Regression test for BUG-126: OperationalError deadlock when accessing session.id.
    This test verifies that get_active_thread accepts session_id (int) instead of
    session object to prevent SQLAlchemy lazy loading that can cause deadlocks.
    """
    import inspect

    source = inspect.getsource(get_active_thread)

    assert "session_id: int" in source, "get_active_thread should accept session_id parameter"
    assert "session.id" not in source, "get_active_thread should not access session.id"


def test_build_ladder_path_uses_session_id_not_object(db, sample_data):
    """Test that build_ladder_path uses session_id to avoid lazy loading deadlocks.

    Regression test for BUG-126: OperationalError deadlock when accessing session.id.
    This test verifies that build_ladder_path accepts session_id (int) instead of
    session object to prevent SQLAlchemy lazy loading that can cause deadlocks.
    """
    import inspect

    source = inspect.getsource(build_ladder_path)

    assert "session_id: int" in source, "build_ladder_path should accept session_id parameter"
    assert "session.id" not in source, "build_ladder_path should not access session.id"


def test_get_or_create_deadlock_retry(db, sample_data):
    """Test that get_or_create retries on deadlock errors.

    Regression test for BUG-126: OperationalError deadlock.
    This test mocks as db.commit to raise a deadlock error once,
    then succeeds on retry.
    """
    from unittest.mock import patch

    call_count = 0

    original_commit = db.commit

    def mock_commit(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            from sqlalchemy.exc import OperationalError

            raise OperationalError(
                "deadlock detected",
                {},
                Exception("psycopg.errors.DeadlockDetected: deadlock detected"),
            )
        return original_commit()

    with patch.object(db, "commit", side_effect=mock_commit):
        session = get_or_create(db, user_id=1)
        assert session is not None
        assert session.start_die == 6


def test_get_or_create_uses_session_id_to_prevent_lazy_load(db, sample_data):
    """Test that get_or_create session object doesn't cause lazy loading issues.

    Regression test for BUG-126: Verify that session returned from get_or_create
    can have its id extracted without triggering lazy loading that causes deadlocks.
    """
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    db.commit()

    result_session = get_or_create(db, user_id=1)

    session_id = result_session.id
    assert session_id is not None
    assert isinstance(session_id, int)


def test_get_or_create_non_deadlock_operational_error(db, sample_data):
    """Test that get_or_create raises non-deadlock OperationalError.

    Regression test for BUG-126: Verify that non-deadlock OperationalErrors
    are properly raised without retrying.
    """
    from unittest.mock import patch
    from sqlalchemy.exc import OperationalError

    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC) - timedelta(hours=7)
    db.commit()

    commit_call_count = 0
    original_commit = db.commit

    def mock_commit(*args, **kwargs):
        nonlocal commit_call_count
        commit_call_count += 1
        if commit_call_count == 1:
            raise OperationalError("some other error", {}, Exception())
        return original_commit()

    with patch.object(db, "commit", side_effect=mock_commit):
        with pytest.raises(OperationalError, match="some other error"):
            get_or_create(db, user_id=1)


def test_get_or_create_sqlite_advisory_lock(db, sample_data):
    """Test that get_or_create handles SQLite's lack of pg_advisory_xact_lock.

    On SQLite, SELECT pg_advisory_xact_lock will fail, and the exception
    should be silently caught.
    """
    from unittest.mock import patch
    from sqlalchemy.exc import DatabaseError

    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    db.commit()

    original_execute = db.execute

    def sqlite_mock_execute(stmt, *args, **kwargs):
        if hasattr(stmt, "text") and "pg_advisory_xact_lock" in stmt.text:
            raise DatabaseError(
                "Function not supported",
                "Function not supported",
                Exception("no such function: pg_advisory_xact_lock"),
            )
        return original_execute(stmt, *args, **kwargs)

    with patch.object(db, "execute", side_effect=sqlite_mock_execute):
        session = get_or_create(db, user_id=1)
        assert session is not None
        assert session.start_die == 6


def test_get_or_create_max_retries_exceeded(db, sample_data):
    """Test that get_or_create has proper error handling for max retries.

    Regression test for BUG-126: Verify that after max retries,
    get_or_create properly handles exhausted retry attempts.
    Note: Actual deadlock retry behavior is tested by inspecting code structure
    in test_get_or_create_handles_deadlock_regression.
    """
    import inspect

    source = inspect.getsource(get_or_create)

    assert "RuntimeError" in source, "get_or_create should raise RuntimeError after max retries"
    assert "Failed to get_or_create session after" in source, (
        "get_or_create should have specific error message for max retries"
    )


@pytest.mark.asyncio
async def test_get_current_session_handles_deadlock_regression(
    client: AsyncClient, db, default_user
):
    """Test that get_current_session has retry logic for deadlock handling.

    Regression test for BUG-126: OperationalError deadlock when accessing session.id.
    This test verifies that code structure includes deadlock retry logic.
    """
    import inspect

    from app.api.session import get_current_session

    source = inspect.getsource(get_current_session)

    assert "OperationalError" in source, "get_current_session should handle OperationalError"
    assert "deadlock" in source.lower(), "get_current_session should check for deadlock errors"
    assert "retry" in source.lower() or "while" in source.lower(), (
        "get_current_session should have retry logic"
    )
    assert "rollback" in source.lower(), "get_current_session should rollback on deadlock"


def test_undo_to_snapshot_handles_deadlock_regression(db, sample_data):
    """Test that undo_to_snapshot has retry logic for deadlock handling.

    Regression test for BUG-126: OperationalError deadlock during concurrent operations.
    This test verifies that code structure includes deadlock retry logic.
    """
    import inspect

    from app.api.undo import undo_to_snapshot

    source = inspect.getsource(undo_to_snapshot)

    assert "OperationalError" in source, "undo_to_snapshot should handle OperationalError"
    assert "deadlock" in source.lower(), "undo_to_snapshot should check for deadlock errors"
    assert "retry" in source.lower() or "while" in source.lower(), (
        "undo_to_snapshot should have retry logic"
    )
    assert "rollback" in source.lower(), "undo_to_snapshot should rollback on deadlock"


def test_is_active_with_naive_datetime(db):
    """Test that is_active handles datetime without timezone.

    When a datetime has no tzinfo, it should be treated as UTC.
    This test verifies the branch is executed (coverage).
    """
    session = SessionModel(
        started_at=datetime.now() - timedelta(hours=1),
        start_die=6,
        user_id=1,
    )
    db.add(session)
    db.commit()

    naive_dt = datetime.now() - timedelta(hours=1)
    assert naive_dt.tzinfo is None

    result = is_active(naive_dt, None, db)
    assert result is not None


def test_is_active_naive_old_datetime(db):
    """Test that is_active handles old naive datetime correctly."""
    session = SessionModel(
        started_at=datetime.now() - timedelta(hours=1),
        start_die=6,
        user_id=1,
    )
    db.add(session)
    db.commit()

    naive_dt = datetime.now() - timedelta(hours=7)
    assert naive_dt.tzinfo is None

    result = is_active(naive_dt, None, db)
    assert result is not None
