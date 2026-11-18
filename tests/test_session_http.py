"""Tests for session HTTP endpoints."""

from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.models import User
from app.models import ReadingSession

async def test_list_sessions(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test listing all sessions with pagination."""
    from app.models import ReadingSession

    for i in range(5):
        session = ReadingSession(
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
    from app.models import ReadingSession

    for i in range(5):
        session = ReadingSession(
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


async def test_session_endpoints_return_404_for_non_owner(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Session resource endpoints return 404 for non-owners."""
    owner_session = ReadingSession(start_die=6, user_id=default_user.id)
    async_db.add(owner_session)
    await async_db.commit()
    await async_db.refresh(owner_session)

    intruder = User(username="session_intruder", created_at=None)
    async_db.add(intruder)
    await async_db.commit()
    await async_db.refresh(intruder)

    intruder_token = create_access_token(data={"sub": intruder.username, "jti": "session-intruder"})
    intruder_headers = {"Authorization": f"Bearer {intruder_token}"}

    details_response = await auth_client.get(
        f"/api/v1/sessions/{owner_session.id}/details",
        headers=intruder_headers,
    )
    assert details_response.status_code == 404
    assert details_response.json()["detail"] == "Session not found"
