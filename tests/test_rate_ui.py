"""Test that both save and continue and finish session are available when issues_remaining is 0."""

import pytest

from httpx import AsyncClient
from app.models import Event, Session as SessionModel, Thread
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_both_buttons_available_when_thread_complete(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
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
        "/api/rate/", json={"rating": 5.0, "issues_read": 1, "finish_session": False}
    )
    assert response.status_code == 200

    await async_db.refresh(thread)
    assert thread.issues_remaining == 0
    assert thread.status == "completed"  # Thread completes when issues_remaining reaches 0

    await async_db.refresh(session)
    assert (
        session.ended_at is None
    )  # Session should still be active (decoupled from thread completion)

    # Get current session to verify active_thread is still available
    # even though the thread is completed, the session is still active
    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert data["active_thread"]["id"] == thread.id
    assert data["active_thread"]["issues_remaining"] == 0
    assert data["ended_at"] is None  # Session should still be active


@pytest.mark.asyncio
async def test_can_still_rate_after_thread_complete(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """After one thread completes, pending next thread can be resolved and rolled."""
    # Create user
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    # Create session
    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Create thread with 1 issue remaining (will complete)
    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread1)

    # Create another thread with issues remaining (stays active)
    thread2 = Thread(
        title="Thread 2",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    # Create roll event to select thread1
    roll_event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    async_db.add(roll_event)
    await async_db.commit()

    # Rate the last issue of thread1 (issues_remaining becomes 0, thread completes)
    response = await auth_client.post(
        "/api/rate/", json={"rating": 5.0, "issues_read": 1, "finish_session": False}
    )
    assert response.status_code == 200

    await async_db.refresh(thread1)
    assert thread1.issues_remaining == 0
    assert thread1.status == "completed"  # Thread completes when issues_remaining reaches 0

    # Session should still be active
    await async_db.refresh(session)
    assert session.ended_at is None

    # Backend auto-advances a pending thread. Confirm next thread is pending.
    current_session_response = await auth_client.get("/api/sessions/current/")
    assert current_session_response.status_code == 200
    assert current_session_response.json()["pending_thread_id"] == thread2.id

    # Rolling is blocked while pending exists.
    blocked_roll = await auth_client.post("/api/roll/")
    assert blocked_roll.status_code == 409

    # After dismissing pending state, rolling should select thread2.
    dismiss_response = await auth_client.post("/api/roll/dismiss-pending")
    assert dismiss_response.status_code == 204

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200
    data = roll_response.json()
    assert data["thread_id"] == thread2.id
