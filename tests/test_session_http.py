"""Tests for session HTTP endpoints."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.models import Event, Session, Snapshot, Thread, User
from app.models import Session as SessionModel
from comic_pile.session import create_session_start_snapshot

async def test_get_current_session_active(
    client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test getting current active session."""
    from app.auth import create_access_token
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

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

    token = create_access_token(data={"sub": default_user.username, "jti": "test"})
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/v1/sessions/current/", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session.id
    assert data["start_die"] == 6
    assert data["active_thread"] is not None
    assert data["active_thread"]["id"] == thread.id
    assert data["current_die"] == 6

async def test_get_current_session_no_active(
    client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test getting current session creates a new session when none is active."""
    from app.auth import create_access_token
    from app.models import Session as SessionModel

    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC) - timedelta(hours=7),
        ended_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()

    token = create_access_token(data={"sub": default_user.username, "jti": "test"})
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/v1/sessions/current/", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["start_die"] == 6

async def test_list_sessions(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test listing all sessions with pagination."""
    from app.models import Session as SessionModel

    for i in range(5):
        session = SessionModel(
            start_die=6 + i, user_id=default_user.id, started_at=datetime.now(UTC)
        )
        async_db.add(session)
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/?page_size=3")
    assert response.status_code == 200
    data = response.json()
    assert "sessions" in data
    sessions = data["sessions"]
    assert len(sessions) == 3

async def test_list_sessions_pagination(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test session pagination works correctly."""
    import time
    from app.models import Session as SessionModel

    for i in range(5):
        session = SessionModel(
            start_die=6 + i, user_id=default_user.id, started_at=datetime.now(UTC)
        )
        async_db.add(session)
        await async_db.commit()
        time.sleep(0.01)

    first_page = await auth_client.get("/api/v1/sessions/?page_size=2")
    assert first_page.status_code == 200
    first_data = first_page.json()
    assert "sessions" in first_data
    first_sessions = first_data["sessions"]
    assert len(first_sessions) == 2

    next_token = first_data.get("next_page_token")
    assert next_token is not None

    second_page = await auth_client.get("/api/v1/sessions/", params={"page_token": next_token})
    assert second_page.status_code == 200
    second_data = second_page.json()
    assert "sessions" in second_data
    second_sessions = second_data["sessions"]
    assert len(second_sessions) >= 1

    first_ids = {s["id"] for s in first_sessions}
    second_ids = {s["id"] for s in second_sessions}
    assert first_ids.isdisjoint(second_ids), "First and second page should have different sessions"

async def test_get_session_by_id(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test getting a specific session by ID."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session.id
    assert data["start_die"] == 6

async def test_get_session_not_found(auth_client: AsyncClient) -> None:
    """Test getting a non-existent session."""
    response = await auth_client.get("/api/v1/sessions/9999")
    assert response.status_code == 404
    assert "Session not found" in response.json()["detail"]

async def test_get_session_includes_ladder_path(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test session response includes dice ladder path."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    event1 = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(event1)

    event2 = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    async_db.add(event2)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert "6 → 8" in data["ladder_path"]

async def test_get_session_includes_snapshot_info(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test session response includes snapshot count and restore point info."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    async_db.add(event)
    await async_db.commit()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 10}},
        description="After rating",
    )
    async_db.add(snapshot)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["snapshot_count"] == 1
    assert data["has_restore_point"] is True

async def test_session_endpoints_return_404_for_non_owner(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Session resource endpoints return 404 for non-owners."""
    owner_session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(owner_session)
    await async_db.commit()
    await async_db.refresh(owner_session)

    intruder = User(username="session_intruder", created_at=None)
    async_db.add(intruder)
    await async_db.commit()
    await async_db.refresh(intruder)

    intruder_token = create_access_token(data={"sub": intruder.username, "jti": "session-intruder"})
    intruder_headers = {"Authorization": f"Bearer {intruder_token}"}

    get_response = await auth_client.get(
        f"/api/v1/sessions/{owner_session.id}",
        headers=intruder_headers,
    )
    assert get_response.status_code == 404
    assert get_response.json()["detail"] == "Session not found"

    details_response = await auth_client.get(
        f"/api/v1/sessions/{owner_session.id}/details",
        headers=intruder_headers,
    )
    assert details_response.status_code == 404
    assert details_response.json()["detail"] == "Session not found"

    snapshots_response = await auth_client.get(
        f"/api/v1/sessions/{owner_session.id}/snapshots",
        headers=intruder_headers,
    )
    assert snapshots_response.status_code == 404
    assert snapshots_response.json()["detail"] == "Session not found"

    restore_response = await auth_client.post(
        f"/api/v1/sessions/{owner_session.id}/restore-session-start",
        headers=intruder_headers,
    )
    assert restore_response.status_code == 404
    assert restore_response.json()["detail"] == "Session not found"

async def test_get_current_session_after_get_or_create_no_lazy_load(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that accessing session.id after get_or_create doesn't cause MissingGreenlet.

    Regression test for MissingGreenlet error when get_current_session creates a new
    session via get_or_create, which commits during create_session_start_snapshot,
    expiring the session object. Accessing .id on expired session triggers lazy load
    which fails in async context with MissingGreenlet.

    The fix ensures db.refresh() is called before accessing session.id.
    """
    from sqlalchemy import delete

    await async_db.execute(delete(Snapshot))
    await async_db.execute(delete(SessionModel))
    await async_db.commit()

    thread1 = Thread(
        title="Test Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Test Thread 2",
        format="Graphic Novel",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["start_die"] == 6
    assert data["user_id"] == default_user.id

