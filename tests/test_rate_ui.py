"""Test that both save and continue and finish session are available when issues_remaining is 0."""

import pytest

from app.models import Event, Session as SessionModel, Thread


@pytest.mark.asyncio
async def test_both_buttons_available_when_thread_complete(client, db):
    """Both Save & Continue and Finish Session should be available even when issues_remaining is 0."""
    # Create user
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    # Create session
    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    # Create thread with 1 issue remaining
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

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
    db.add(roll_event)
    db.commit()

    # Rate the last issue (issues_remaining becomes 0)
    response = await client.post(
        "/rate/", json={"rating": 5.0, "issues_read": 1, "finish_session": False}
    )
    assert response.status_code == 200

    db.refresh(thread)
    assert thread.issues_remaining == 0
    assert thread.status == "active"  # Should not be completed unless finish_session=True

    db.refresh(session)
    assert session.ended_at is None  # Session should still be active

    # Get current session to verify active_thread is still available
    response = await client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert data["active_thread"]["id"] == thread.id
    assert data["active_thread"]["issues_remaining"] == 0
    assert data["ended_at"] is None  # Session should still be active


@pytest.mark.asyncio
async def test_can_still_rate_after_thread_complete(client, db):
    """After rating last issue, should still be able to rate again if rolled."""
    # Create user
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    # Create session
    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    # Create thread with 1 issue remaining
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

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
    db.add(roll_event)
    db.commit()

    # Rate the last issue (issues_remaining becomes 0)
    response = await client.post(
        "/rate/", json={"rating": 5.0, "issues_read": 1, "finish_session": False}
    )
    assert response.status_code == 200

    db.refresh(thread)
    assert thread.issues_remaining == 0

    # Roll again (should be able to roll thread with 0 issues)
    response = await client.post("/api/roll/")
    assert response.status_code == 200
