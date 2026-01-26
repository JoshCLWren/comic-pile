"""Test that overriding to a snoozed thread removes it from snoozed list."""

from httpx import AsyncClient
import pytest
from sqlalchemy.orm import Session

from app.models import Event, Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_override_snoozed_thread_removes_from_snoozed_list(
    auth_client: AsyncClient, db: Session
) -> None:
    """Overriding to a snoozed thread should remove it from snoozed_thread_ids."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    # Create two threads
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
    db.add(thread1)
    db.add(thread2)
    db.commit()
    db.refresh(thread1)
    db.refresh(thread2)

    # Roll and snooze thread1
    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    # Roll using API to set pending thread
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()
    rolled_thread_id = roll_data["thread_id"]

    # Snooze the rolled thread (which should be thread1, not thread2)
    snooze_response = await auth_client.post("/api/snooze/")
    assert snooze_response.status_code == 200
    snooze_data = snooze_response.json()
    assert rolled_thread_id in snooze_data["snoozed_thread_ids"]

    # Now override to snoozed thread1
    override_response = await auth_client.post("/api/roll/override", json={"thread_id": thread1.id})
    assert override_response.status_code == 200

    # Get current session from API to verify snoozed list was updated
    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()

    # Verify thread1 is no longer in snoozed list
    assert thread1.id not in session_data["snoozed_thread_ids"], (
        f"Thread {thread1.id} should be removed from snoozed list, got {session_data['snoozed_thread_ids']}"
    )
