"""Tests for rate API endpoints."""

import pytest
from sqlalchemy import select

from app.models import Event, Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_rate_success(auth_client, db):
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

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    data = response.json()
    assert data["issues_remaining"] == 4
    assert data["last_rating"] == 4.0

    db.refresh(thread)
    assert thread.issues_remaining == 4
    assert thread.last_rating == 4.0


@pytest.mark.asyncio
async def test_rate_low_rating(auth_client, db):
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

    response = await auth_client.post("/api/rate/", json={"rating": 3.0, "issues_read": 1})
    assert response.status_code == 200

    events = (
        db.execute(select(Event).where(Event.session_id == session.id).where(Event.type == "rate"))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].die_after == 12


@pytest.mark.asyncio
async def test_rate_high_rating(auth_client, db):
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

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    events = (
        db.execute(select(Event).where(Event.session_id == session.id).where(Event.type == "rate"))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].die_after == 8


@pytest.mark.asyncio
async def test_rate_completes_thread(auth_client, db):
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

    response = await auth_client.post(
        "/api/rate/", json={"rating": 4.0, "issues_read": 1, "finish_session": True}
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
async def test_rate_records_event(auth_client, db):
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

    response = await auth_client.post("/api/rate/", json={"rating": 4.5, "issues_read": 2})
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
async def test_rate_no_active_session(auth_client):
    """Returns error if no active session."""
    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 400
    assert "No active session" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rate_no_active_thread(auth_client, db):
    """Returns error if no active thread in session."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 400
    assert "No active thread" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rate_updates_manual_die(auth_client, db):
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

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    db.refresh(session)
    assert session.manual_die == 8


@pytest.mark.asyncio
async def test_rate_low_rating_updates_manual_die(auth_client, db):
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

    response = await auth_client.post("/api/rate/", json={"rating": 3.0, "issues_read": 1})
    assert response.status_code == 200

    db.refresh(session)
    assert session.manual_die == 8


@pytest.mark.asyncio
async def test_rate_finish_session_flag_controls_session_end(auth_client, db):
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

    response = await auth_client.post(
        "/api/rate/", json={"rating": 4.0, "issues_read": 1, "finish_session": False}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["status"] != "completed"
    assert data["issues_remaining"] == 0

    db.refresh(thread)
    assert thread.status != "completed"

    db.refresh(session)
    assert session.ended_at is None


def test_rating_settings_returns_defaults(monkeypatch):
    """Test rating settings return default values."""
    from app.config import clear_settings_cache, get_rating_settings

    # Clear any cached settings and env vars
    for var in ["RATING_MIN", "RATING_MAX", "RATING_THRESHOLD"]:
        monkeypatch.delenv(var, raising=False)
    clear_settings_cache()

    settings = get_rating_settings()
    assert settings.rating_min == 0.5
    assert settings.rating_max == 5.0
    assert settings.rating_threshold == 4.0


def test_rating_settings_returns_custom_values(monkeypatch):
    """Test rating settings return custom values when set."""
    from app.config import clear_settings_cache, get_rating_settings

    monkeypatch.setenv("RATING_MIN", "1.0")
    monkeypatch.setenv("RATING_MAX", "4.5")
    monkeypatch.setenv("RATING_THRESHOLD", "3.5")
    clear_settings_cache()

    settings = get_rating_settings()
    assert settings.rating_min == 1.0
    assert settings.rating_max == 4.5
    assert settings.rating_threshold == 3.5


def test_rating_settings_validates_range(monkeypatch):
    """Test rating settings validate and clamp to valid range."""
    from app.config import clear_settings_cache, get_rating_settings

    # Values outside range get clamped by validators
    monkeypatch.setenv("RATING_MIN", "10.0")
    monkeypatch.setenv("RATING_MAX", "15.0")
    monkeypatch.setenv("RATING_THRESHOLD", "-1.0")
    clear_settings_cache()

    settings = get_rating_settings()
    # Validators clamp out-of-range values to defaults
    assert settings.rating_min == 0.5
    assert settings.rating_max == 5.0
    assert settings.rating_threshold == 4.0
