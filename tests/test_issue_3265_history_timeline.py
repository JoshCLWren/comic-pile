"""Regression tests for issue #3265: history timeline deleted-thread placeholder and duplicate events."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.models import Event, Issue, ReadingSession, Thread


@pytest.mark.asyncio
async def test_session_details_deduplicates_identical_events(auth_client, async_db) -> None:
    """Duplicate event pairs at the same timestamp must appear once."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session = ReadingSession(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Add a roll event twice with identical content (simulating double-logging).
    for _ in range(2):
        event = Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=None,
            die=6,
            result=4,
            selection_method="random",
            timestamp=datetime(2026, 10, 4, 21, 12, tzinfo=UTC),
        )
        async_db.add(event)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    events = data.get("events", [])
    roll_events = [e for e in events if e["type"] == "roll"]
    assert len(roll_events) == 1, f"Expected 1 roll event after dedup, got {len(roll_events)}"


@pytest.mark.asyncio
async def test_session_details_deleted_thread_shows_graceful_placeholder(auth_client, async_db) -> None:
    """When a roll references a deleted thread, the timeline should not say 'Thread unavailable'."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session = ReadingSession(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Create a thread and an issue, then delete the thread after logging the event.
    thread = Thread(
        title="Flash",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    issue = Issue(thread_id=thread.id, issue_number="1", status="unread", position=1)
    async_db.add(issue)
    await async_db.commit()

    event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=10,
        result=1,
        selection_method="random",
        issue_id=issue.id,
        issue_number="1",
        timestamp=datetime(2026, 10, 4, 21, 12, tzinfo=UTC),
    )
    async_db.add(event)
    await async_db.commit()

    # Delete the thread so the foreign reference is broken.
    await async_db.execute(delete(Thread).where(Thread.id == thread.id))
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    roll_events = [e for e in data.get("events", []) if e["type"] == "roll"]
    assert len(roll_events) == 1
    assert roll_events[0]["thread_title"] is None or roll_events[0]["thread_title"] == ""
    # The frontend uses issue_number to render a graceful placeholder.
    assert roll_events[0]["issue_number"] == "1"
