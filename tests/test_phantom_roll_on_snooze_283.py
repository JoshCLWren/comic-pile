"""Test for issue 283: phantom roll events on snooze."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_snooze_does_not_create_roll_event(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Snoozing a thread should NOT create a roll event in session history.

    This test verifies that when a user snoozes a thread from the action sheet,
    only a "snooze" event is created, not a phantom "roll" event.

    Regression test for issue #283.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    # Create a session
    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Create a thread
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

    # Roll the dice - this creates a "roll" event
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()
    assert roll_data["thread_id"] == thread.id

    # Verify we have exactly 1 roll event
    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id).where(Event.type == "roll")
    )
    roll_events_before_snooze = result.scalars().all()
    assert len(roll_events_before_snooze) == 1, "Should have exactly 1 roll event after rolling"

    # Simulate what the frontend does when snoozing from action sheet:
    # First calls setPending (creates a manual roll event), then calls snooze
    # This is the bug - it creates a phantom roll event!
    set_pending_response = await auth_client.post(f"/api/threads/{thread.id}/set-pending")
    assert set_pending_response.status_code == 200

    # Now snooze the thread
    snooze_response = await auth_client.post("/api/snooze/")
    assert snooze_response.status_code == 200

    # Verify we STILL have exactly 1 roll event (no phantom roll event created)
    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id).where(Event.type == "roll")
    )
    roll_events_after_snooze = result.scalars().all()
    assert len(roll_events_after_snooze) == 1, "Snoozing should NOT create an additional roll event"

    # Verify a snooze event was created
    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id).where(Event.type == "snooze")
    )
    snooze_events = result.scalars().all()
    assert len(snooze_events) == 1, "Should have exactly 1 snooze event"
    assert snooze_events[0].thread_id == thread.id

    # Also verify via the session details API endpoint
    details_response = await auth_client.get(f"/api/sessions/{session.id}/details")
    assert details_response.status_code == 200
    details_data = details_response.json()

    # Count roll events in the session details
    roll_events_in_details = [e for e in details_data["events"] if e["type"] == "roll"]
    assert len(roll_events_in_details) == 1, (
        "Session details should show exactly 1 roll event, not a phantom roll event"
    )
