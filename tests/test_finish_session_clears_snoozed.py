"""Tests that finishing a session clears snoozed_thread_ids."""

import pytest

from app.models import Event, Thread
from httpx import AsyncClient
from app.models import Session as SessionModel
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_finish_session_clears_snoozed_threads(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Finishing a session clears snoozed_thread_ids from the session."""
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
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    # Roll thread1
    event1 = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    async_db.add(event1)
    session.pending_thread_id = thread1.id
    await async_db.commit()

    # Snooze thread1 (die steps up to d8, thread1 added to snoozed list)
    snooze_response = await auth_client.post("/api/snooze/")
    assert snooze_response.status_code == 200
    snooze_data = snooze_response.json()
    assert thread1.id in snooze_data["snoozed_thread_ids"]
    assert snooze_data["manual_die"] == 8

    # Roll thread2
    event2 = Event(
        type="roll",
        die=8,
        result=1,
        selected_thread_id=thread2.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread2.id,
    )
    async_db.add(event2)
    session.pending_thread_id = thread2.id
    await async_db.commit()

    # Rate thread2 with finish_session=True to finish the session
    rate_response = await auth_client.post(
        "/api/rate/", json={"rating": 4.0, "issues_read": 1, "finish_session": True}
    )
    assert rate_response.status_code == 200

    await async_db.refresh(session)
    # Session should be ended
    assert session.ended_at is not None

    # snoozed_thread_ids should be cleared when session finishes
    assert session.snoozed_thread_ids is None or len(session.snoozed_thread_ids) == 0
