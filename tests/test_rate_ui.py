"""Test that both save and continue and finish session are available when issues_remaining is 0."""

import pytest

from httpx import AsyncClient
from app.models import Event, Session as SessionModel, Thread
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_both_buttons_available_when_thread_complete(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Both Save & Continue and Finish Session should be available even when issues_remaining is 0."""
    # Create user
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    # Create session
    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Create thread with 1 issue remaining
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    # Create roll event to select the thread
    roll_event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(roll_event)
    await async_db.commit()

    # Rate the last issue (issues_remaining becomes 0)
    response = await auth_client.post(
        "/api/v1/rate/", json={"rating": 5.0, "issues_read": 1, "finish_session": False}
    )
    assert response.status_code == 200

    await async_db.refresh(thread)
    assert thread.issues_remaining == 0
    assert thread.status == "active"  # Should not be completed unless finish_session=True

    await async_db.refresh(session)
    assert session.ended_at is None  # Session should still be active

    # Get current session to verify active_thread is still available
    response = await auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert data["active_thread"]["id"] == thread.id
    assert data["active_thread"]["issues_remaining"] == 0
    assert data["ended_at"] is None  # Session should still be active


@pytest.mark.asyncio
async def test_can_still_rate_after_thread_complete(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """After rating last issue, should still be able to rate again if rolled."""
    # Create user
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    # Create session
    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Create thread with 1 issue remaining
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    # Create roll event to select the thread
    roll_event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(roll_event)
    await async_db.commit()

    # Rate the last issue (issues_remaining becomes 0)
    response = await auth_client.post(
        "/api/v1/rate/", json={"rating": 5.0, "issues_read": 1, "finish_session": False}
    )
    assert response.status_code == 200

    await async_db.refresh(thread)
    assert thread.issues_remaining == 0

    # Roll again (should be able to roll thread with 0 issues)
    response = await auth_client.post("/api/v1/roll/")
    assert response.status_code == 200
