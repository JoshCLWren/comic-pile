"""Tests for snooze API endpoints."""

import pytest
from sqlalchemy import select

from app.models import Event, Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_snooze_success(auth_client, db):
    """POST /snooze/ snoozes pending thread and steps die up."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

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
    db.add(event)
    session.pending_thread_id = thread.id
    db.commit()

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200

    data = response.json()
    # Thread added to snoozed_thread_ids
    assert thread.id in data["snoozed_thread_ids"]
    # Die stepped UP (d6 → d8)
    assert data["manual_die"] == 8
    # snoozed_threads includes thread info
    snoozed_titles = [t["title"] for t in data["snoozed_threads"]]
    assert "Test Thread" in snoozed_titles

    # Verify pending_thread_id is cleared
    db.refresh(session)
    assert session.pending_thread_id is None

    # Verify snooze event was recorded
    snooze_event = (
        db.execute(
            select(Event).where(Event.session_id == session.id).where(Event.type == "snooze")
        )
        .scalars()
        .first()
    )
    assert snooze_event is not None
    assert snooze_event.thread_id == thread.id
    assert snooze_event.die == 6
    assert snooze_event.die_after == 8


@pytest.mark.asyncio
async def test_snooze_no_pending_thread(auth_client, db):
    """POST /snooze/ returns 400 if no thread has been rolled."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    # Create session without pending_thread_id
    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    db.commit()

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 400
    assert "No pending thread to snooze" in response.json()["detail"]


@pytest.mark.asyncio
async def test_snooze_no_session(auth_client):
    """POST /snooze/ returns 400 if no active session exists."""
    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 400
    assert "No active session" in response.json()["detail"]


@pytest.mark.asyncio
async def test_snooze_excludes_from_roll(auth_client, db):
    """After snoozing a thread, it is excluded from subsequent rolls."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

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

    # Set up pending thread and snooze it
    event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    db.add(event)
    session.pending_thread_id = thread1.id
    db.commit()

    # Snooze thread1
    snooze_response = await auth_client.post("/api/snooze/")
    assert snooze_response.status_code == 200

    # Roll again - should only get thread2
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200

    roll_data = roll_response.json()
    assert roll_data["thread_id"] == thread2.id
    assert roll_data["title"] == "Thread Two"


@pytest.mark.asyncio
async def test_snooze_duplicate_thread(auth_client, db):
    """Snoozing the same thread twice doesn't add duplicate to list."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    # Second thread so we can still roll after snoozing
    thread2 = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.add(thread2)
    db.commit()
    db.refresh(thread)
    db.refresh(thread2)

    # First snooze
    event1 = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event1)
    session.pending_thread_id = thread.id
    db.commit()

    response1 = await auth_client.post("/api/snooze/")
    assert response1.status_code == 200

    # Roll again (will get thread2)
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200

    # Manually set pending_thread_id back to the already-snoozed thread
    # (simulating an override select)
    db.refresh(session)
    session.pending_thread_id = thread.id
    event2 = Event(
        type="roll",
        die=8,
        result=1,
        selected_thread_id=thread.id,
        selection_method="override",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event2)
    db.commit()

    # Second snooze of the same thread
    response2 = await auth_client.post("/api/snooze/")
    assert response2.status_code == 200

    data = response2.json()
    # Count occurrences of thread.id in snoozed_thread_ids
    snoozed_count = data["snoozed_thread_ids"].count(thread.id)
    assert snoozed_count == 1, "Duplicate thread should not be added to snoozed list"


@pytest.mark.asyncio
async def test_snooze_all_threads(auth_client, db):
    """Snoozing all threads causes roll to return 400 error."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    # Create only one thread
    thread = Thread(
        title="Only Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    # Roll and snooze the only thread
    event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    session.pending_thread_id = thread.id
    db.commit()

    snooze_response = await auth_client.post("/api/snooze/")
    assert snooze_response.status_code == 200

    # Verify the thread is snoozed
    snooze_data = snooze_response.json()
    assert thread.id in snooze_data["snoozed_thread_ids"]

    # Now try to roll - should fail with no threads available
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 400
    assert "No active threads" in roll_response.json()["detail"]


@pytest.mark.asyncio
async def test_snooze_steps_die_up_from_max(auth_client, db):
    """Snooze at max die (d20) keeps die at d20."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=20, manual_die=20, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        die=20,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    session.pending_thread_id = thread.id
    db.commit()

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200

    data = response.json()
    # Die should stay at d20 (max)
    assert data["manual_die"] == 20


@pytest.mark.asyncio
async def test_snooze_multiple_different_threads(auth_client, db):
    """Snoozing multiple different threads accumulates in list."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

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
    db.add(thread1)
    db.add(thread2)
    db.add(thread3)
    db.commit()
    db.refresh(thread1)
    db.refresh(thread2)
    db.refresh(thread3)

    # Roll and snooze thread1
    event1 = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    db.add(event1)
    session.pending_thread_id = thread1.id
    db.commit()

    response1 = await auth_client.post("/api/snooze/")
    assert response1.status_code == 200
    data1 = response1.json()
    assert thread1.id in data1["snoozed_thread_ids"]
    assert len(data1["snoozed_thread_ids"]) == 1

    # Roll and snooze thread2
    event2 = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread2.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread2.id,
    )
    db.add(event2)
    session.pending_thread_id = thread2.id
    db.commit()

    response2 = await auth_client.post("/api/snooze/")
    assert response2.status_code == 200
    data2 = response2.json()
    assert thread1.id in data2["snoozed_thread_ids"]
    assert thread2.id in data2["snoozed_thread_ids"]
    assert len(data2["snoozed_thread_ids"]) == 2

    # Roll and snooze thread3
    event3 = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread3.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread3.id,
    )
    db.add(event3)
    session.pending_thread_id = thread3.id
    db.commit()

    response3 = await auth_client.post("/api/snooze/")
    assert response3.status_code == 200
    data3 = response3.json()
    assert thread1.id in data3["snoozed_thread_ids"]
    assert thread2.id in data3["snoozed_thread_ids"]
    assert thread3.id in data3["snoozed_thread_ids"]
    assert len(data3["snoozed_thread_ids"]) == 3
