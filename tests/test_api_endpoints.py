"""API endpoint integration tests."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@pytest.mark.asyncio
async def test_create_thread(auth_client, db):
    """Test POST /api/threads/ creates new thread."""
    thread_data = {
        "title": "Spider-Man",
        "format": "Comic",
        "issues_remaining": 12,
    }
    response = await auth_client.post("/api/threads/", json=thread_data)
    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "Spider-Man"
    assert data["format"] == "Comic"
    assert data["issues_remaining"] == 12
    assert data["position"] == 1
    assert data["status"] == "active"
    assert "id" in data
    assert "created_at" in data

    from app.models import Thread

    thread = db.execute(select(Thread).where(Thread.title == "Spider-Man")).scalar_one_or_none()
    assert thread is not None
    assert thread.title == "Spider-Man"


@pytest.mark.asyncio
async def test_create_thread_validation(auth_client):
    """Test POST /api/threads/ validates input."""
    invalid_data = {
        "title": "",
        "format": "Comic",
        "issues_remaining": 12,
    }
    response = await auth_client.post("/api/threads/", json=invalid_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_threads(auth_client, sample_data):
    """Test GET /api/threads/ returns all threads."""
    response = await auth_client.get("/api/threads/")
    assert response.status_code == 200

    threads = response.json()
    assert len(threads) == 5
    assert threads[0]["title"] == "Superman"
    assert threads[1]["title"] == "Batman"
    assert threads[2]["title"] == "Wonder Woman"
    assert threads[3]["title"] == "Flash"
    assert threads[4]["title"] == "Aquaman"


@pytest.mark.asyncio
async def test_list_threads_empty(auth_client):
    """Test GET /api/threads/ with no threads returns empty list."""
    response = await auth_client.get("/api/threads/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_thread(auth_client, sample_data):
    """Test GET /api/threads/{id} returns single thread."""
    response = await auth_client.get("/api/threads/1")
    assert response.status_code == 200

    thread = response.json()
    assert thread["id"] == 1
    assert thread["title"] == "Superman"
    assert thread["format"] == "Comic"
    assert thread["issues_remaining"] == 10
    assert thread["position"] == 1
    assert thread["status"] == "active"


@pytest.mark.asyncio
async def test_get_thread_not_found(auth_client):
    """Test GET /api/threads/{id} returns 404 for non-existent thread."""
    response = await auth_client.get("/api/threads/999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_thread(auth_client, sample_data, db):
    """Test PUT /api/threads/{id} updates thread."""
    update_data = {
        "title": "Superman Updated",
        "format": "Trade Paperback",
        "issues_remaining": 8,
    }
    response = await auth_client.put("/api/threads/1", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["id"] == 1
    assert thread["title"] == "Superman Updated"
    assert thread["format"] == "Trade Paperback"
    assert thread["issues_remaining"] == 8

    from app.models import Thread

    db_thread = db.get(Thread, 1)
    assert db_thread.title == "Superman Updated"
    assert db_thread.format == "Trade Paperback"
    assert db_thread.issues_remaining == 8


@pytest.mark.asyncio
async def test_update_thread_partial(auth_client, sample_data):
    """Test PUT /api/threads/{id} with partial data."""
    update_data = {
        "title": "Batman Updated",
    }
    response = await auth_client.put("/api/threads/2", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["title"] == "Batman Updated"
    assert thread["format"] == "Comic"
    assert thread["issues_remaining"] == 5


@pytest.mark.asyncio
async def test_update_thread_not_found(auth_client):
    """Test PUT /api/threads/{id} returns 404 for non-existent thread."""
    update_data = {
        "title": "Non-existent",
    }
    response = await auth_client.put("/api/threads/999", json=update_data)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_thread_complete_status(auth_client, sample_data, db):
    """Test PUT /api/threads/{id} sets completed status when issues_remaining is 0."""
    update_data = {
        "issues_remaining": 0,
    }
    response = await auth_client.put("/api/threads/1", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["status"] == "completed"
    assert thread["issues_remaining"] == 0

    from app.models import Thread

    db_thread = db.get(Thread, 1)
    assert db_thread.status == "completed"


@pytest.mark.asyncio
async def test_update_thread_active_status(auth_client, sample_data, db):
    """Test PUT /api/threads/{id} sets active status when issues_remaining > 0."""
    update_data = {
        "issues_remaining": 5,
    }
    response = await auth_client.put("/api/threads/3", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["status"] == "active"
    assert thread["issues_remaining"] == 5

    from app.models import Thread

    db_thread = db.get(Thread, 3)
    assert db_thread.status == "active"


@pytest.mark.asyncio
async def test_delete_thread(auth_client, sample_data, db):
    """Test DELETE /api/threads/{id} removes thread."""
    response = await auth_client.delete("/api/threads/1")
    assert response.status_code == 204

    from app.models import Thread

    db_thread = db.get(Thread, 1)
    assert db_thread is None

    response = await auth_client.get("/api/threads/1")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_thread_not_found(auth_client):
    """Test DELETE /api/threads/{id} returns 404 for non-existent thread."""
    response = await auth_client.delete("/api/threads/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_thread_cascades_to_events_and_snapshots(
    sample_data, db: Session, auth_client
):
    """Test that deleting a thread also deletes associated events and snapshots."""
    from datetime import UTC, datetime

    from app.models import Event, Session as SessionModel, Snapshot, Thread, User

    now = datetime.now(UTC)
    user = db.execute(select(User).where(User.id == 1)).scalar_one()
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=100,
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    session = SessionModel(start_die=6, user_id=user.id, started_at=now)
    db.add(session)
    db.commit()
    db.refresh(session)

    event = Event(
        type="roll",
        die=6,
        result=4,
        session_id=session.id,
        thread_id=thread.id,
        timestamp=now,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={"1": {"title": "Test Thread"}},
        description="Test snapshot",
    )
    db.add(snapshot)
    db.commit()

    response = await auth_client.delete(f"/api/threads/{thread.id}")
    assert response.status_code == 204

    db_thread = db.get(Thread, thread.id)
    assert db_thread is None

    db_event = db.get(Event, event.id)
    assert db_event is None

    snapshot_count_after = db.execute(
        select(func.count(Snapshot.id)).where(Snapshot.event_id == event.id)
    ).scalar()
    assert snapshot_count_after == 0


@pytest.mark.asyncio
async def test_get_session_current(auth_client, db):
    """Test GET /session/current/ returns active session."""
    from datetime import UTC, datetime

    from app.models import Session as SessionModel, User

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one()
    session = SessionModel(start_die=6, user_id=user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200

    session_data = response.json()
    assert session_data["id"] == session.id
    assert session_data["start_die"] == 6
    assert session_data["user_id"] == user.id
    assert "ladder_path" in session_data


@pytest.mark.asyncio
async def test_get_session_current_creates_session(auth_client, db):
    """Test GET /api/sessions/current/ creates new session when none exists."""
    from app.models import Session as SessionModel

    initial_count = db.execute(select(func.count()).select_from(SessionModel)).scalar()

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200

    session_data = response.json()
    assert "id" in session_data
    assert "start_die" in session_data

    final_count = db.execute(select(func.count()).select_from(SessionModel)).scalar()
    assert final_count == initial_count + 1


@pytest.mark.asyncio
async def test_get_session_current_uses_selected_thread_id(auth_client, db):
    """Test GET /sessions/current/ returns active thread from selected_thread_id."""
    from datetime import UTC, datetime

    from app.models import Event, Thread, User
    from app.models import Session as SessionModel

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=datetime.now(UTC))
        db.add(user)
        db.commit()
        db.refresh(user)

    thread = Thread(
        title="Saga",
        format="TPB",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    session = SessionModel(start_die=6, user_id=user.id, started_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    db.refresh(session)

    event = Event(
        type="roll",
        die=6,
        result=2,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=None,
        timestamp=datetime.now(UTC),
    )
    db.add(event)
    db.commit()

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200

    data = response.json()
    assert data["active_thread"]["id"] == thread.id
    assert data["active_thread"]["title"] == "Saga"


@pytest.mark.asyncio
async def test_get_sessions(auth_client, sample_data):
    """Test GET /sessions/ lists all sessions."""
    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200

    sessions = response.json()
    assert len(sessions) == 2
    assert {s["start_die"] for s in sessions} == {6, 8}


@pytest.mark.asyncio
async def test_get_sessions_pagination(auth_client, sample_data):
    """Test GET /sessions/ with pagination."""
    response = await auth_client.get("/api/sessions/?limit=1&offset=0")
    assert response.status_code == 200

    sessions = response.json()
    assert len(sessions) == 1


@pytest.mark.asyncio
async def test_get_session(auth_client, sample_data):
    """Test GET /sessions/{id} returns single session."""
    response = await auth_client.get("/api/sessions/1")
    assert response.status_code == 200

    session = response.json()
    assert session["id"] == 1
    assert session["start_die"] == 6
    assert session["user_id"] == 1
    assert "ladder_path" in session


@pytest.mark.asyncio
async def test_get_session_not_found(auth_client):
    """Test GET /sessions/{id} returns 404 for non-existent session."""
    response = await auth_client.get("/api/sessions/999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_session_details(auth_client, sample_data):
    """Test GET /sessions/{id}/details returns events as JSON."""
    response = await auth_client.get("/api/sessions/1/details")
    assert response.status_code == 200

    data = response.json()
    assert data["session_id"] == 1
    assert "events" in data
    assert len(data["events"]) > 0


@pytest.mark.asyncio
async def test_get_stale_threads(auth_client, db):
    """Test GET /api/threads/stale returns threads inactive for specified days."""
    from datetime import datetime, timedelta

    from app.models import Thread, User

    now = datetime.now()

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=datetime.now())
        db.add(user)
        db.commit()
        db.refresh(user)

    stale_thread = Thread(
        title="Old Thread",
        format="Comic",
        status="active",
        queue_position=1,
        last_activity_at=now - timedelta(days=10),
        user_id=user.id,
    )
    recent_thread = Thread(
        title="Recent Thread",
        format="Comic",
        status="active",
        queue_position=2,
        last_activity_at=now - timedelta(days=3),
        user_id=user.id,
    )
    no_activity_thread = Thread(
        title="No Activity Thread",
        format="Comic",
        status="active",
        queue_position=3,
        last_activity_at=None,
        user_id=user.id,
    )

    db.add_all([stale_thread, recent_thread, no_activity_thread])
    db.commit()

    response = await auth_client.get("/api/threads/stale?days=7")
    assert response.status_code == 200

    stale = response.json()
    assert len(stale) == 2
    stale_ids = [t["id"] for t in stale]
    assert stale_thread.id in stale_ids
    assert no_activity_thread.id in stale_ids
    assert recent_thread.id not in stale_ids


@pytest.mark.asyncio
async def test_get_stale_threads_custom_threshold(auth_client, db):
    """Test GET /api/threads/stale with custom days parameter."""
    from datetime import datetime, timedelta

    from app.models import Thread, User

    now = datetime.now()

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=datetime.now())
        db.add(user)
        db.commit()
        db.refresh(user)

    thread_5_days = Thread(
        title="5 Days Old",
        format="Comic",
        status="active",
        queue_position=1,
        last_activity_at=now - timedelta(days=5),
        user_id=user.id,
    )
    thread_15_days = Thread(
        title="15 Days Old",
        format="Comic",
        status="active",
        queue_position=2,
        last_activity_at=now - timedelta(days=15),
        user_id=user.id,
    )

    db.add_all([thread_5_days, thread_15_days])
    db.commit()

    response = await auth_client.get("/api/threads/stale?days=10")
    assert response.status_code == 200

    stale = response.json()
    assert len(stale) == 1
    assert stale[0]["id"] == thread_15_days.id
    assert stale[0]["title"] == "15 Days Old"


@pytest.mark.asyncio
async def test_create_thread_with_notes(auth_client, db):
    """Test POST /api/threads/ creates thread with notes."""
    thread_data = {
        "title": "Batman",
        "format": "Comic",
        "issues_remaining": 20,
        "notes": "Favorite series, must read regularly",
    }
    response = await auth_client.post("/api/threads/", json=thread_data)
    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "Batman"
    assert data["format"] == "Comic"
    assert data["issues_remaining"] == 20
    assert data["notes"] == "Favorite series, must read regularly"
    assert "id" in data

    from app.models import Thread

    thread = db.execute(select(Thread).where(Thread.title == "Batman")).scalar_one_or_none()
    assert thread is not None
    assert thread.notes == "Favorite series, must read regularly"


@pytest.mark.asyncio
async def test_create_thread_without_notes(auth_client, db):
    """Test POST /api/threads/ creates thread without notes (nullable)."""
    thread_data = {
        "title": "Superman",
        "format": "Comic",
        "issues_remaining": 15,
    }
    response = await auth_client.post("/api/threads/", json=thread_data)
    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "Superman"
    assert data["format"] == "Comic"
    assert data["issues_remaining"] == 15
    assert data["notes"] is None

    from app.models import Thread

    thread = db.execute(select(Thread).where(Thread.title == "Superman")).scalar_one_or_none()
    assert thread is not None
    assert thread.notes is None


@pytest.mark.asyncio
async def test_update_thread_notes(auth_client, sample_data, db):
    """Test PUT /api/threads/{id} updates thread notes."""
    update_data = {
        "notes": "Updated notes: Need to catch up on back issues",
    }
    response = await auth_client.put("/api/threads/1", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["id"] == 1
    assert thread["title"] == "Superman"
    assert thread["notes"] == "Updated notes: Need to catch up on back issues"

    from app.models import Thread

    db_thread = db.get(Thread, 1)
    assert db_thread.notes == "Updated notes: Need to catch up on back issues"


@pytest.mark.asyncio
async def test_get_thread_includes_notes(auth_client, sample_data, db):
    """Test GET /api/threads/{id} includes notes field."""
    from datetime import datetime

    from app.models import Thread, User

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one()
    thread = Thread(
        title="Wonder Woman",
        format="Comic",
        issues_remaining=8,
        queue_position=1,
        status="active",
        user_id=user.id,
        notes="Important character, historical significance",
        created_at=datetime.now(),
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    response = await auth_client.get(f"/api/threads/{thread.id}")
    assert response.status_code == 200

    thread_data = response.json()
    assert thread_data["id"] == thread.id
    assert thread_data["title"] == "Wonder Woman"
    assert thread_data["notes"] == "Important character, historical significance"


@pytest.mark.asyncio
async def test_list_threads_includes_notes(auth_client, sample_data, db):
    """Test GET /api/threads/ includes notes field in all threads."""
    from datetime import datetime

    from app.models import Thread, User

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one()
    thread_with_notes = Thread(
        title="Flash",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        notes="Fast-paced storytelling",
        created_at=datetime.now(),
    )
    thread_without_notes = Thread(
        title="Aquaman",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        user_id=user.id,
        notes=None,
        created_at=datetime.now(),
    )
    db.add_all([thread_with_notes, thread_without_notes])
    db.commit()

    response = await auth_client.get("/api/threads/")
    assert response.status_code == 200

    threads = response.json()
    assert len(threads) >= 2

    flash_thread = next((t for t in threads if t["title"] == "Flash"), None)
    aquaman_thread = next((t for t in threads if t["title"] == "Aquaman"), None)

    assert flash_thread is not None
    assert flash_thread["notes"] == "Fast-paced storytelling"

    assert aquaman_thread is not None
    assert aquaman_thread["notes"] is None


@pytest.mark.asyncio
async def test_delete_thread_clears_pending_thread_id(auth_client, db: Session):
    """Test that deleting a thread clears pending_thread_id from sessions."""
    from datetime import datetime

    from app.models import Session as SessionModel, Thread, User

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one()
    thread = Thread(
        title="Batman",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(),
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    session = SessionModel(start_die=6, user_id=user.id, pending_thread_id=thread.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    assert session.pending_thread_id == thread.id

    response = await auth_client.delete(f"/api/threads/{thread.id}")

    assert response.status_code == 204

    db_thread = db.get(Thread, thread.id)
    assert db_thread is None

    db.refresh(session)
    assert session.pending_thread_id is None


@pytest.mark.asyncio
async def test_delete_thread_integrity_error_pending_thread_id(auth_client, db: Session):
    """Regression test for BUG-131: IntegrityError when deleting thread with pending_thread_id.

    This test verifies that deleting a thread that has sessions with pending_thread_id
    set does not cause a ForeignViolation error. The fix ensures that the UPDATE
    to clear pending_thread_id is flushed before the DELETE executes.
    """
    from datetime import datetime

    from app.models import Session as SessionModel, Thread, User

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one()
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    session = SessionModel(
        start_die=6,
        user_id=user.id,
        pending_thread_id=thread.id,
        started_at=datetime.now(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    assert session.pending_thread_id == thread.id

    response = await auth_client.delete(f"/api/threads/{thread.id}")

    assert response.status_code == 204, (
        f"Expected 204, got {response.status_code}: {response.text if hasattr(response, 'text') else ''}"
    )

    db_thread = db.get(Thread, thread.id)
    assert db_thread is None

    db.refresh(session)
    assert session.pending_thread_id is None
