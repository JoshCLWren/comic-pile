"""Integration tests for rate API endpoint."""

import pytest

from httpx import AsyncClient
from app.models import Event, ReadingSession, Thread
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_rate_session_api_returns_thread_info(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /sessions/current/ returns active thread info for rate page."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Amazing Spider-Man",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=4,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "active_thread" in data
    assert data["active_thread"]["id"] == thread.id
    assert data["active_thread"]["title"] == "Amazing Spider-Man"
    assert data["active_thread"]["format"] == "Comic"
    assert data["active_thread"]["issues_remaining"] == 10


@pytest.mark.asyncio
async def test_rate_session_api_returns_die_info(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /sessions/current/ returns die info for dice preview."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=3,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "current_die" in data
    assert data["current_die"] == 10
    assert "last_rolled_result" in data
    assert data["last_rolled_result"] == 3


@pytest.mark.asyncio
async def test_rate_session_api_returns_has_restore_point(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /sessions/current/ returns has_restore_point for session safe indicator."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "has_restore_point" in data
    assert isinstance(data["has_restore_point"], bool)
