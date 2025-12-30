"""Tests for rate API endpoints."""

from sqlalchemy import select

from app.models import Event, Session as SessionModel, Thread


async def test_rate_success(client, db, sample_data):
    """POST /rate/ updates thread correctly."""
    from app.models import User

    user = User(id=1, username="test_user")
    db.add(user)

    session = SessionModel(start_die=10, user_id=1)
    db.add(session)

    thread = Thread(
        id=10,
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
    )
    db.add(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=10,
        selection_method="random",
        session_id=session.id,
        thread_id=10,
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


async def test_rate_low_rating(client, db, sample_data):
    """Rating=3.0, die_size steps down."""
    from app.models import User

    user = User(id=1, username="test_user")
    db.add(user)

    session = SessionModel(start_die=10, user_id=1)
    db.add(session)

    thread = Thread(
        id=11,
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
    )
    db.add(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=11,
        selection_method="random",
        session_id=session.id,
        thread_id=11,
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
    assert events[0].die_after == 8


async def test_rate_high_rating(client, db, sample_data):
    """Rating=4.0, die_size steps up."""
    from app.models import User

    user = User(id=1, username="test_user")
    db.add(user)

    session = SessionModel(start_die=10, user_id=1)
    db.add(session)

    thread = Thread(
        id=12,
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
    )
    db.add(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=12,
        selection_method="random",
        session_id=session.id,
        thread_id=12,
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
    assert events[0].die_after == 12


async def test_rate_completes_thread(client, db, sample_data):
    """Issues <= 0, moves to back of queue, session ends."""
    from app.models import User

    user = User(id=1, username="test_user")
    db.add(user)

    session = SessionModel(start_die=10, user_id=1)
    db.add(session)

    thread = Thread(
        id=13,
        title="Test Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=1,
    )
    db.add(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=13,
        selection_method="random",
        session_id=session.id,
        thread_id=13,
    )
    db.add(event)
    db.commit()

    response = await client.post("/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"
    assert data["issues_remaining"] == 0

    db.refresh(thread)
    assert thread.status == "completed"
    assert thread.queue_position == 5

    db.refresh(session)
    assert session.ended_at is not None


async def test_rate_records_event(client, db, sample_data):
    """Event saved with rating and issues_read."""
    from app.models import User

    user = User(id=1, username="test_user")
    db.add(user)

    session = SessionModel(start_die=10, user_id=1)
    db.add(session)

    thread = Thread(
        id=14,
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
    )
    db.add(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=14,
        selection_method="random",
        session_id=session.id,
        thread_id=14,
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


async def test_rate_no_active_session(client, db, sample_data):
    """Returns error if no active session."""
    from app.models import User

    user = User(id=1, username="test_user")
    db.add(user)
    db.commit()

    response = await client.post("/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 400
    assert "No active session" in response.json()["detail"]


async def test_rate_no_active_thread(client, db, sample_data):
    """Returns error if no active thread in session."""
    from app.models import User

    user = User(id=1, username="test_user")
    db.add(user)

    session = SessionModel(start_die=10, user_id=1)
    db.add(session)
    db.commit()

    response = await client.post("/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 400
    assert "No active thread" in response.json()["detail"]
