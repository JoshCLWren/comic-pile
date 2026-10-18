"""Test that overriding to a snoozed thread succeeds and preserves the snooze."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


from app.models import ReadingSession
from app.models import Thread


@pytest.mark.asyncio
async def test_override_snoozed_thread_keeps_it_snoozed(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit override of a snoozed thread succeeds without losing its snooze.

    The Roll "Pick manually" picker surfaces a "Snoozed series" group on purpose, so an
    override of a snoozed thread must succeed (issue #3446). The durable session snooze is
    read state and is deliberately preserved, so the thread stays snoozed afterwards (#293).
    """
    from tests.conftest import get_or_create_user_async

    monkeypatch.setattr("random.randint", lambda _a, _b: 0)

    user = await get_or_create_user_async(async_db)

    # Create thread (single thread to ensure deterministic roll)
    thread1 = Thread(
        title="Thread One",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread1)
    await async_db.commit()
    await async_db.refresh(thread1)

    # Roll and snooze thread1
    session = ReadingSession(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Roll using API to set pending thread
    roll_response = await auth_client.post("/api/v1/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()
    rolled_thread_id = roll_data["thread_id"]

    # Snooze the rolled thread (thread1)
    snooze_response = await auth_client.post("/api/v1/snooze/")
    assert snooze_response.status_code == 200
    snooze_data = snooze_response.json()
    assert rolled_thread_id in snooze_data["snoozed_thread_ids"]

    # Overriding a snoozed thread is allowed and returns it as the current thread.
    override_response = await auth_client.post(
        "/api/v1/roll/override", json={"thread_id": thread1.id}
    )
    assert override_response.status_code == 200, override_response.text
    assert override_response.json()["thread_id"] == thread1.id

    # The snooze is preserved: the explicit override must not clear durable read state.
    session_response = await auth_client.get("/api/v1/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()

    assert thread1.id in session_data["snoozed_thread_ids"], (
        f"Thread {thread1.id} should remain in snoozed list, got {session_data['snoozed_thread_ids']}"
    )
