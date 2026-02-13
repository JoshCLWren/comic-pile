"""Tests for safe mode session navigation feature."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import Event, Session as SessionModel, Snapshot, Thread, User


@pytest_asyncio.fixture(scope="function")
async def safe_mode_user(async_db: AsyncSession) -> User:
    """Create a test user for safe mode tests."""
    result = await async_db.execute(select(User).where(User.username == "safe_mode_user"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(username="safe_mode_user", created_at=datetime.now(UTC))
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def safe_mode_auth_client(
    async_db: AsyncSession, safe_mode_user: User
) -> AsyncGenerator[AsyncClient]:
    """httpx.AsyncClient authenticated as safe_mode_user for safe mode tests."""
    from app.auth import create_access_token
    from app.database import get_db

    from tests.conftest import _create_async_db_override

    app.dependency_overrides[get_db] = await _create_async_db_override(async_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        token = create_access_token(data={"sub": safe_mode_user.username, "jti": "test"})
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_session_response_has_restore_point_true(
    safe_mode_auth_client: AsyncClient, async_db: AsyncSession, safe_mode_user: User
) -> None:
    """Test that SessionResponse correctly reports has_restore_point when snapshots exist."""
    session = SessionModel(start_die=6, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=safe_mode_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=None,
        thread_states={thread.id: {"issues_remaining": 10, "queue_position": 1}},
        description="Session start",
    )
    async_db.add(snapshot)
    await async_db.commit()

    response = await safe_mode_auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["has_restore_point"] is True
    assert data["snapshot_count"] == 1


@pytest.mark.asyncio
async def test_session_response_has_restore_point_false(
    safe_mode_auth_client: AsyncClient, async_db: AsyncSession, safe_mode_user: User
) -> None:
    """Test that SessionResponse correctly reports has_restore_point when no snapshots exist."""
    session = SessionModel(start_die=6, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await safe_mode_auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["has_restore_point"] is False
    assert data["snapshot_count"] == 0


@pytest.mark.asyncio
async def test_current_session_response_includes_restore_point(
    safe_mode_auth_client: AsyncClient, async_db: AsyncSession, safe_mode_user: User
) -> None:
    """Test that /sessions/current/ includes has_restore_point field."""
    session = SessionModel(start_die=6, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=safe_mode_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=None,
        thread_states={thread.id: {"issues_remaining": 10, "queue_position": 1}},
        description="Session start",
    )
    async_db.add(snapshot)
    await async_db.commit()

    response = await safe_mode_auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "has_restore_point" in data
    assert data["has_restore_point"] is True
    assert data["snapshot_count"] == 1


@pytest.mark.asyncio
async def test_list_sessions_includes_restore_point_for_each(
    safe_mode_auth_client: AsyncClient, async_db: AsyncSession, safe_mode_user: User
) -> None:
    """Test that /sessions/ includes has_restore_point for all sessions."""
    session1 = SessionModel(start_die=6, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    session2 = SessionModel(start_die=8, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    async_db.add_all([session1, session2])
    await async_db.commit()
    await async_db.refresh(session1)
    await async_db.refresh(session2)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=safe_mode_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    snapshot = Snapshot(
        session_id=session1.id,
        event_id=None,
        thread_states={thread.id: {"issues_remaining": 10, "queue_position": 1}},
        description="Session start",
    )
    async_db.add(snapshot)
    await async_db.commit()

    response = await safe_mode_auth_client.get("/api/v1/sessions/")
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
    safe_mode_auth_client: AsyncClient, async_db: AsyncSession, safe_mode_user: User
) -> None:
    """Test that snapshot_count correctly counts all snapshots."""
    session = SessionModel(start_die=6, user_id=safe_mode_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=safe_mode_user.id,
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
    async_db.add_all([snapshot1, snapshot2])
    await async_db.commit()

    response = await safe_mode_auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["has_restore_point"] is True
    assert data["snapshot_count"] == 2
