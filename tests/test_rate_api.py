"""Tests for rate API endpoints."""

import pytest
from sqlalchemy import select

from app.models import Event, Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_rate_success(client, db):
    """POST /rate/ updates thread correctly."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
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
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.post("/rate/", json={"rating": 4.0, "issues_read": 2})
    assert response.status_code == 200

    data = response.json()
    assert data["issues_remaining"] == 3
    assert data["last_rating"] == 4.0

    db.refresh(thread)
    assert thread.issues_remaining == 3
    assert thread.last_rating == 4.0


@pytest.mark.asyncio
async def test_rate_low_rating(client, db):
    """Rating=3.0, die_size steps up."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
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
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.post("/rate/", json={"rating": 3.0, "issues_read": 1})
    assert response.status_code == 200

    events = (
        db.execute(select(Event).where(Event.session_id == session.id).where(Event.type == "rate"))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].die_after == 12


@pytest.mark.asyncio
async def test_rate_high_rating(client, db):
    """Rating=4.0, die_size steps down."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
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
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.post("/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    events = (
        db.execute(select(Event).where(Event.session_id == session.id).where(Event.type == "rate"))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].die_after == 8


@pytest.mark.asyncio
async def test_rate_completes_thread(client, db):
    """Issues <= 0, moves to back of queue, session ends only with finish_session=True."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

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

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.post(
        "/rate/", json={"rating": 4.0, "issues_read": 1, "finish_session": True}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"
    assert data["issues_remaining"] == 0

    db.refresh(thread)
    assert thread.status == "completed"
    assert thread.queue_position == 1

    db.refresh(session)
    assert session.ended_at is not None


@pytest.mark.asyncio
async def test_rate_records_event(client, db):
    """Event saved with rating and issues_read."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
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
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.post("/rate/", json={"rating": 4.5, "issues_read": 2})
    assert response.status_code == 200

    events = (
        db.execute(select(Event).where(Event.session_id == session.id).where(Event.type == "rate"))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].rating == 4.5
    assert events[0].issues_read == 2


@pytest.mark.asyncio
async def test_rate_no_active_session(client, db):
    """Returns error if no active session."""
    response = await client.post("/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 400
    assert "No active session" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rate_no_active_thread(client, db):
    """Returns error if no active thread in session."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    response = await client.post("/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 400
    assert "No active thread" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rate_updates_manual_die(client, db):
    """Rating updates session manual_die to die_after value."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, manual_die=20, user_id=user.id)
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
    db.commit()

    response = await client.post("/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    db.refresh(session)
    assert session.manual_die == 8


@pytest.mark.asyncio
async def test_rate_low_rating_updates_manual_die(client, db):
    """Low rating steps die up and updates manual_die."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=6, manual_die=6, user_id=user.id)
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
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.post("/rate/", json={"rating": 3.0, "issues_read": 1})
    assert response.status_code == 200

    db.refresh(session)
    assert session.manual_die == 8


@pytest.mark.asyncio
async def test_rate_finish_session_flag_controls_session_end(client, db):
    """finish_session=False keeps session active even when thread completes."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

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

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.post(
        "/rate/", json={"rating": 4.0, "issues_read": 1, "finish_session": False}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["status"] != "completed"
    assert data["issues_remaining"] == 0

    db.refresh(thread)
    assert thread.status != "completed"

    db.refresh(session)
    assert session.ended_at is None
