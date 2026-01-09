"""Tests for safe mode session navigation feature."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Event, Session as SessionModel, Snapshot, Thread, User
from datetime import UTC, datetime


@pytest.fixture(scope="function")
def safe_mode_user(db) -> User:
    """Create a test user for safe mode tests."""
    user = db.execute(select(User).where(User.username == "safe_mode_user")).scalar_one_or_none()
    if not user:
        user = User(username="safe_mode_user", created_at=datetime.now(UTC))
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_session_response_has_restore_point_true(client: AsyncClient, db, safe_mode_user):
    """Test that SessionResponse correctly reports has_restore_point when snapshots exist."""
    session = SessionModel(start_die=6, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=safe_mode_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=None,
        thread_states={thread.id: {"issues_remaining": 10, "queue_position": 1}},
        description="Session start",
    )
    db.add(snapshot)
    db.commit()

    response = await client.get(f"/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["has_restore_point"] is True
    assert data["snapshot_count"] == 1


@pytest.mark.asyncio
async def test_session_response_has_restore_point_false(client: AsyncClient, db, safe_mode_user):
    """Test that SessionResponse correctly reports has_restore_point when no snapshots exist."""
    session = SessionModel(start_die=6, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    response = await client.get(f"/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["has_restore_point"] is False
    assert data["snapshot_count"] == 0


@pytest.mark.asyncio
async def test_current_session_response_includes_restore_point(
    client: AsyncClient, db, safe_mode_user
):
    """Test that /sessions/current/ includes has_restore_point field."""
    session = SessionModel(start_die=6, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=safe_mode_user.id,
    )
    db.add(thread)
    db.commit()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=None,
        thread_states={thread.id: {"issues_remaining": 10, "queue_position": 1}},
        description="Session start",
    )
    db.add(snapshot)
    db.commit()

    response = await client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "has_restore_point" in data
    assert data["has_restore_point"] is True
    assert data["snapshot_count"] == 1


@pytest.mark.asyncio
async def test_list_sessions_includes_restore_point_for_each(
    client: AsyncClient, db, safe_mode_user
):
    """Test that /sessions/ includes has_restore_point for all sessions."""
    session1 = SessionModel(start_die=6, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    session2 = SessionModel(start_die=8, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    db.add_all([session1, session2])
    db.commit()
    db.refresh(session1)
    db.refresh(session2)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=safe_mode_user.id,
    )
    db.add(thread)
    db.commit()

    snapshot = Snapshot(
        session_id=session1.id,
        event_id=None,
        thread_states={thread.id: {"issues_remaining": 10, "queue_position": 1}},
        description="Session start",
    )
    db.add(snapshot)
    db.commit()

    response = await client.get("/api/sessions/")
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2

    session1_data = next((s for s in sessions if s["id"] == session1.id), None)
    session2_data = next((s for s in sessions if s["id"] == session2.id), None)

    assert session1_data is not None
    assert session1_data["has_restore_point"] is True
    assert session1_data["snapshot_count"] == 1

    assert session2_data is not None
    assert session2_data["has_restore_point"] is False
    assert session2_data["snapshot_count"] == 0


@pytest.mark.asyncio
async def test_snapshot_count_increases_with_multiple_snapshots(
    client: AsyncClient, db, safe_mode_user
):
    """Test that snapshot_count correctly counts all snapshots."""
    session = SessionModel(start_die=6, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=safe_mode_user.id,
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

    snapshot1 = Snapshot(
        session_id=session.id,
        event_id=None,
        thread_states={thread.id: {"issues_remaining": 10}},
        description="Session start",
    )
    snapshot2 = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 9}},
        description="After rating",
    )
    db.add_all([snapshot1, snapshot2])
    db.commit()

    response = await client.get(f"/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["has_restore_point"] is True
    assert data["snapshot_count"] == 2
