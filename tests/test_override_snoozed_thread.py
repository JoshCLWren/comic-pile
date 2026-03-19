"""Test that overriding to a snoozed thread removes it from snoozed list."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


from app.models import Session as SessionModel
from app.models import Thread


@pytest.mark.asyncio
async def test_override_snoozed_thread_removes_from_snoozed_list(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overriding to a snoozed thread should be rejected to prevent data loss."""
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
    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Roll using API to set pending thread
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()
    rolled_thread_id = roll_data["thread_id"]

    # Snooze the rolled thread (thread1)
    snooze_response = await auth_client.post("/api/snooze/")
    assert snooze_response.status_code == 200
    snooze_data = snooze_response.json()
    assert rolled_thread_id in snooze_data["snoozed_thread_ids"]

    # Now override to snoozed thread1
    # This should fail because we should not be able to override to a snoozed thread
    override_response = await auth_client.post("/api/roll/override", json={"thread_id": thread1.id})

    # The override should be rejected with an error
    assert override_response.status_code == 400
    assert "snoozed" in override_response.json()["detail"].lower()

    # Get current session from API to verify thread remains in snoozed list
    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()

    # Verify thread1 is still in snoozed list (data was NOT lost)
    assert thread1.id in session_data["snoozed_thread_ids"], (
        f"Thread {thread1.id} should remain in snoozed list, got {session_data['snoozed_thread_ids']}"
    )
