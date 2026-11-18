"""Tests for session HTTP endpoints."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.models import Event, Snapshot, Thread, User
from app.models import ReadingSession

async def test_get_current_session_active(
    client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test getting current active session."""
    from app.models import ReadingSession

    session = ReadingSession(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
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
    from app.models import ReadingSession

    session = ReadingSession(
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
    await async_db.execute(delete(ReadingSession))
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
