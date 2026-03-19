"""Tests for unsnooze API endpoint."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_unsnooze_success(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """POST /snooze/{thread_id}/unsnooze removes thread from snoozed list.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    # Create a roll event to set up pending_thread_id
    event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    session.pending_thread_id = thread.id
    await async_db.commit()

    # First, snooze the thread
    snooze_response = await auth_client.post("/api/snooze/")
    assert snooze_response.status_code == 200
    snooze_data = snooze_response.json()
    assert thread.id in snooze_data["snoozed_thread_ids"]

    # Now unsnooze it
    unsnooze_response = await auth_client.post(f"/api/snooze/{thread.id}/unsnooze")
    assert unsnooze_response.status_code == 200

    data = unsnooze_response.json()
    # Thread removed from snoozed_thread_ids
    assert thread.id not in data["snoozed_thread_ids"]
    # snoozed_threads no longer includes this thread
    snoozed_titles = [t["title"] for t in data["snoozed_threads"]]
    assert "Test Thread" not in snoozed_titles

    # Verify unsnooze event was recorded
    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id).where(Event.type == "unsnooze")
    )
    unsnooze_event = result.scalars().first()
    assert unsnooze_event is not None
    assert unsnooze_event.thread_id == thread.id


@pytest.mark.asyncio
async def test_unsnooze_non_snoozed_thread_returns_404(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """POST /snooze/{thread_id}/unsnooze returns 404 when thread is not snoozed.

    This is a regression test for issue #285.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Create a thread that is NOT snoozed
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    # Attempt to unsnooze a thread that was never snoozed
    response = await auth_client.post(f"/api/snooze/{thread.id}/unsnooze")

    # Should return 404 (not found), not 200 (silent no-op)
    assert response.status_code == 404
    assert "not snoozed" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_unsnooze_no_session(auth_client: AsyncClient) -> None:
    """POST /snooze/{thread_id}/unsnooze returns 400 if no active session exists.

    Args:
        auth_client: Authenticated HTTP client for API requests.
    """
    response = await auth_client.post("/api/snooze/999/unsnooze")
    assert response.status_code == 400
    assert "No active session" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unsnooze_multiple_snoozed_threads(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Unsnoozing one thread does not affect other snoozed threads.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread1 = Thread(
        title="Thread One",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    thread2 = Thread(
        title="Thread Two",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    thread3 = Thread(
        title="Thread Three",
        format="Comic",
        issues_remaining=5,
        queue_position=3,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread1)
    async_db.add(thread2)
    async_db.add(thread3)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)
    await async_db.refresh(thread3)

    # Snooze all three threads
    for thread in [thread1, thread2, thread3]:
        event = Event(
            type="roll",
            die=6,
            result=1,
            selected_thread_id=thread.id,
            selection_method="random",
            session_id=session.id,
            thread_id=thread.id,
        )
        async_db.add(event)
        session.pending_thread_id = thread.id
        await async_db.commit()

        response = await auth_client.post("/api/snooze/")
        assert response.status_code == 200

    # Verify all three are snoozed
    check_response = await auth_client.get("/api/sessions/current/")
    check_data = check_response.json()
    assert len(check_data["snoozed_thread_ids"]) == 3

    # Unsnooze thread2 only
    unsnooze_response = await auth_client.post(f"/api/snooze/{thread2.id}/unsnooze")
    assert unsnooze_response.status_code == 200

    data = unsnooze_response.json()
    # thread2 removed, but thread1 and thread3 remain
    assert thread2.id not in data["snoozed_thread_ids"]
    assert thread1.id in data["snoozed_thread_ids"]
    assert thread3.id in data["snoozed_thread_ids"]
    assert len(data["snoozed_thread_ids"]) == 2
