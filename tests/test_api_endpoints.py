"""API endpoint integration tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as SessionModel, Thread


@pytest.mark.asyncio
async def test_create_thread(auth_client: AsyncClient, async_db: AsyncSession) -> None:
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
    assert data["queue_position"] == 1
    assert data["status"] == "active"
    assert "id" in data
    assert "created_at" in data

    from app.models import Thread

    result = await async_db.execute(select(Thread).where(Thread.title == "Spider-Man"))
    thread = result.scalar_one_or_none()
    assert thread is not None
    assert thread.title == "Spider-Man"


@pytest.mark.asyncio
async def test_create_thread_validation(auth_client: AsyncClient) -> None:
    """Test POST /api/threads/ validates input."""
    invalid_data = {
        "title": "",
        "format": "Comic",
        "issues_remaining": 12,
    }
    response = await auth_client.post("/api/threads/", json=invalid_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_threads(auth_client: AsyncClient, sample_data: dict) -> None:
    """Test GET /api/threads/ returns all threads."""
    _ = sample_data
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
async def test_list_threads_search(auth_client: AsyncClient, sample_data: dict) -> None:
    """Test GET /api/threads/?search= filters threads by title."""
    _ = sample_data

    response = await auth_client.get("/api/threads/", params={"search": "man"})
    assert response.status_code == 200

    threads = response.json()
    titles = {thread["title"] for thread in threads}
    assert titles == {"Superman", "Batman", "Aquaman", "Wonder Woman"}


@pytest.mark.asyncio
async def test_list_threads_empty(auth_client: AsyncClient) -> None:
    """Test GET /api/threads/ with no threads returns empty list."""
    response = await auth_client.get("/api/threads/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_thread(auth_client: AsyncClient, sample_data: dict) -> None:
    """Test GET /api/threads/{id} returns single thread."""
    _ = sample_data
    response = await auth_client.get("/api/threads/1")
    assert response.status_code == 200

    thread = response.json()
    assert thread["id"] == 1
    assert thread["title"] == "Superman"
    assert thread["format"] == "Comic"
    assert thread["issues_remaining"] == 10
    assert thread["queue_position"] == 1
    assert thread["status"] == "active"


@pytest.mark.asyncio
async def test_get_thread_not_found(auth_client: AsyncClient) -> None:
    """Test GET /api/threads/{id} returns 404 for non-existent thread."""
    response = await auth_client.get("/api/threads/999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_thread(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Test PUT /api/threads/{id} updates thread."""
    _ = sample_data
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

    db_thread = await async_db.get(Thread, 1)
    assert db_thread is not None
    assert db_thread.title == "Superman Updated"
    assert db_thread.format == "Trade Paperback"
    assert db_thread.issues_remaining == 8


@pytest.mark.asyncio
async def test_update_thread_partial(auth_client: AsyncClient, sample_data: dict) -> None:
    """Test PUT /api/threads/{id} with partial data."""
    _ = sample_data
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
async def test_update_thread_not_found(auth_client: AsyncClient) -> None:
    """Test PUT /api/threads/{id} returns 404 for non-existent thread."""
    update_data = {
        "title": "Non-existent",
    }
    response = await auth_client.put("/api/threads/999", json=update_data)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_thread_complete_status(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Test PUT /api/threads/{id} sets completed status when issues_remaining is 0."""
    _ = sample_data
    update_data = {
        "issues_remaining": 0,
    }
    response = await auth_client.put("/api/threads/1", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["status"] == "completed"
    assert thread["issues_remaining"] == 0

    from app.models import Thread

    db_thread = await async_db.get(Thread, 1)
    assert db_thread is not None
    assert db_thread.status == "completed"


@pytest.mark.asyncio
async def test_update_thread_active_status(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Test PUT /api/threads/{id} sets active status when issues_remaining > 0."""
    _ = sample_data
    update_data = {
        "issues_remaining": 5,
    }
    response = await auth_client.put("/api/threads/3", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["status"] == "active"
    assert thread["issues_remaining"] == 5

    from app.models import Thread

    db_thread = await async_db.get(Thread, 3)
    assert db_thread is not None
    assert db_thread.status == "active"


@pytest.mark.asyncio
async def test_delete_thread(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Test DELETE /api/threads/{id} removes thread."""
    _ = sample_data
    response = await auth_client.delete("/api/threads/1")
    assert response.status_code == 204

    from app.models import Thread

    db_thread = await async_db.get(Thread, 1)
    assert db_thread is None

    response = await auth_client.get("/api/threads/1")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_thread_not_found(auth_client: AsyncClient) -> None:
    """Test DELETE /api/threads/{id} returns 404 for non-existent thread."""
    response = await auth_client.delete("/api/threads/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_thread_cascades_to_events_and_snapshots(
    sample_data: dict, async_db: AsyncSession, auth_client: AsyncClient
) -> None:
    """Test that deleting a thread also deletes associated events and snapshots."""
    _ = sample_data
    from datetime import UTC, datetime

    from app.models import Event, Session as SessionModel, Snapshot, Thread, User

    now = datetime.now(UTC)
    result = await async_db.execute(select(User).where(User.id == 1))
    user = result.scalar_one()
    user_id = user.id  # Extract before commit

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=100,
        status="active",
        user_id=user_id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)
    thread_id = thread.id  # Extract before next commit

    session = SessionModel(start_die=6, user_id=user_id, started_at=now)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)
    session_id = session.id  # Extract before next commit

    event = Event(
        type="roll",
        die=6,
        result=4,
        session_id=session_id,
        thread_id=thread_id,
        timestamp=now,
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)
    event_id = event.id  # Extract before next commit

    snapshot = Snapshot(
        session_id=session_id,
        event_id=event_id,
        thread_states={"1": {"title": "Test Thread"}},
        description="Test snapshot",
    )
    async_db.add(snapshot)
    await async_db.commit()

    response = await auth_client.delete(f"/api/threads/{thread_id}")
    assert response.status_code == 204

    db_thread = await async_db.get(Thread, thread_id)
    assert db_thread is None

    db_event = await async_db.get(Event, event_id)
    assert db_event is None

    result = await async_db.execute(
        select(func.count(Snapshot.id)).where(Snapshot.event_id == event_id)
    )
    snapshot_count_after = result.scalar()
    assert snapshot_count_after == 0


@pytest.mark.asyncio
async def test_get_session_current(
    auth_client: AsyncClient, async_db: AsyncSession, test_username: str
) -> None:
    """Test GET /session/current/ returns active session."""
    from datetime import UTC, datetime

    from app.models import Session as SessionModel, User

    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()
    session = SessionModel(start_die=6, user_id=user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200

    session_data = response.json()
    assert session_data["id"] == session.id
    assert session_data["start_die"] == 6
    assert session_data["user_id"] == user.id
    assert "ladder_path" in session_data


@pytest.mark.asyncio
async def test_get_session_current_creates_session(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test GET /api/sessions/current/ creates new session when none exists."""
    from app.models import Session as SessionModel

    initial_count_result = await async_db.execute(select(func.count()).select_from(SessionModel))
    initial_count = initial_count_result.scalar()

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200

    session_data = response.json()
    assert "id" in session_data
    assert "start_die" in session_data

    final_count_result = await async_db.execute(select(func.count()).select_from(SessionModel))
    final_count = final_count_result.scalar()
    assert final_count == initial_count + 1


@pytest.mark.asyncio
async def test_get_session_current_uses_selected_thread_id(
    auth_client: AsyncClient, async_db: AsyncSession, test_username: str
) -> None:
    """Test GET /sessions/current/ returns active thread from selected_thread_id."""
    from datetime import UTC, datetime

    from app.models import Event, Thread, User
    from app.models import Session as SessionModel

    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one_or_none()
    if not user:
        user = User(username=test_username, created_at=datetime.now(UTC))
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)

    thread = Thread(
        title="Saga",
        format="TPB",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    session = SessionModel(start_die=6, user_id=user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

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
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200

    data = response.json()
    assert data["active_thread"]["id"] == thread.id
    assert data["active_thread"]["title"] == "Saga"


@pytest.mark.asyncio
async def test_get_session_current_prefers_pending_thread_over_last_roll(
    auth_client: AsyncClient, async_db: AsyncSession, test_username: str
) -> None:
    """GET /sessions/current should surface pending_thread_id as active_thread."""
    from datetime import UTC, datetime

    from app.models import Event, Thread, User
    from app.models import Session as SessionModel

    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one_or_none()
    if not user:
        user = User(username=test_username, created_at=datetime.now(UTC))
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)

    first_thread = Thread(
        title="First",
        format="TPB",
        issues_remaining=4,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    pending_thread = Thread(
        title="Pending",
        format="TPB",
        issues_remaining=8,
        queue_position=2,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add_all([first_thread, pending_thread])
    await async_db.commit()
    await async_db.refresh(first_thread)
    await async_db.refresh(pending_thread)

    session = SessionModel(
        start_die=6,
        user_id=user.id,
        pending_thread_id=pending_thread.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    roll_event = Event(
        type="roll",
        die=6,
        result=3,
        selected_thread_id=first_thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=None,
        timestamp=datetime.now(UTC),
    )
    async_db.add(roll_event)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200

    data = response.json()
    assert data["pending_thread_id"] == pending_thread.id
    assert data["active_thread"]["id"] == pending_thread.id
    assert data["active_thread"]["title"] == "Pending"
    assert data["last_rolled_result"] == 3


@pytest.mark.asyncio
async def test_get_session_current_returns_no_active_thread_when_pending_is_stale(
    auth_client: AsyncClient, async_db: AsyncSession, test_username: str
) -> None:
    """GET /sessions/current should not fall back to roll event when pending thread is stale."""
    from datetime import UTC, datetime

    from app.models import Event, Thread, User
    from app.models import Session as SessionModel

    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one_or_none()
    if not user:
        user = User(username=test_username, created_at=datetime.now(UTC))
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)

    rolled_thread = Thread(
        title="Rolled",
        format="TPB",
        issues_remaining=4,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(rolled_thread)
    await async_db.commit()
    await async_db.refresh(rolled_thread)

    other_user = User(username=f"{test_username}_other", created_at=datetime.now(UTC))
    async_db.add(other_user)
    await async_db.commit()
    await async_db.refresh(other_user)

    other_user_thread = Thread(
        title="Other User Pending",
        format="TPB",
        issues_remaining=6,
        queue_position=1,
        status="active",
        user_id=other_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(other_user_thread)
    await async_db.commit()
    await async_db.refresh(other_user_thread)

    session = SessionModel(
        start_die=6,
        user_id=user.id,
        pending_thread_id=other_user_thread.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    roll_event = Event(
        type="roll",
        die=6,
        result=2,
        selected_thread_id=rolled_thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=None,
        timestamp=datetime.now(UTC),
    )
    async_db.add(roll_event)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200

    data = response.json()
    assert data["pending_thread_id"] == other_user_thread.id
    assert data["active_thread"] is None
    assert data["last_rolled_result"] is None


@pytest.mark.asyncio
async def test_get_sessions(auth_client: AsyncClient, sample_data: dict) -> None:
    """Test GET /sessions/ lists all sessions."""
    _ = sample_data
    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200

    sessions = response.json()
    assert len(sessions) == 2
    assert {s["start_die"] for s in sessions} == {6, 8}


@pytest.mark.asyncio
async def test_get_sessions_pagination(auth_client: AsyncClient, sample_data: dict) -> None:
    """Test GET /sessions/ with pagination."""
    _ = sample_data
    response = await auth_client.get("/api/sessions/?limit=1&offset=0")
    assert response.status_code == 200

    sessions = response.json()
    assert len(sessions) == 1


@pytest.mark.asyncio
async def test_get_session(auth_client: AsyncClient, sample_data: dict) -> None:
    """Test GET /sessions/{id} returns single session."""
    _ = sample_data
    response = await auth_client.get("/api/sessions/1")
    assert response.status_code == 200

    session = response.json()
    assert session["id"] == 1
    assert session["start_die"] == 6
    assert session["user_id"] == 1
    assert "ladder_path" in session


@pytest.mark.asyncio
async def test_get_session_not_found(auth_client: AsyncClient) -> None:
    """Test GET /sessions/{id} returns 404 for non-existent session."""
    response = await auth_client.get("/api/sessions/999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_session_details(auth_client: AsyncClient, sample_data: dict) -> None:
    """Test GET /sessions/{id}/details returns events as JSON."""
    _ = sample_data
    response = await auth_client.get("/api/sessions/1/details")
    assert response.status_code == 200

    data = response.json()
    assert data["session_id"] == 1
    assert "events" in data
    assert len(data["events"]) > 0


@pytest.mark.asyncio
async def test_get_thread_with_notes(
    auth_client: AsyncClient, async_db: AsyncSession, test_username: str
) -> None:
    """Test GET /api/threads/{id} returns thread with notes field."""
    from datetime import UTC, datetime

    from app.models import Thread, User

    result = await async_db.execute(select(User).where(User.username == test_username))
    user = result.scalar_one_or_none()
    if not user:
        user = User(username=test_username, created_at=datetime.now(UTC))
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)

    thread = Thread(
        title="Wonder Woman",
        format="Comic",
        issues_remaining=8,
        queue_position=1,
        status="active",
        user_id=user.id,
        notes="Important character, historical significance",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.get(f"/api/threads/{thread.id}")
    assert response.status_code == 200

    thread_data = response.json()
    assert thread_data["id"] == thread.id
    assert thread_data["title"] == "Wonder Woman"
    assert thread_data["notes"] == "Important character, historical significance"


@pytest.mark.asyncio
async def test_list_threads_includes_notes(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession, test_username: str
) -> None:
    """Test GET /api/threads/ includes notes field in all threads."""
    _ = sample_data
    from datetime import UTC, datetime

    from app.models import Thread, User

    result = await async_db.execute(select(User).where(User.username == test_username))
    user = result.scalar_one()
    thread_with_notes = Thread(
        title="Flash",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        notes="Fast-paced storytelling",
        created_at=datetime.now(UTC),
    )
    thread_without_notes = Thread(
        title="Aquaman",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        user_id=user.id,
        notes=None,
        created_at=datetime.now(UTC),
    )
    async_db.add_all([thread_with_notes, thread_without_notes])
    await async_db.commit()

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
async def test_delete_thread_clears_pending_thread_id(
    auth_client: AsyncClient, async_db: AsyncSession, test_username: str
) -> None:
    """Test that deleting a thread clears pending_thread_id from sessions."""
    from datetime import UTC, datetime

    from app.models import Session as SessionModel, Thread, User

    result = await async_db.execute(select(User).where(User.username == test_username))
    user = result.scalar_one()
    thread = Thread(
        title="Batman",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    session = SessionModel(
        start_die=6, user_id=user.id, pending_thread_id=thread.id, started_at=datetime.now(UTC)
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    assert session.pending_thread_id == thread.id

    response = await auth_client.delete(f"/api/threads/{thread.id}")

    assert response.status_code == 204

    db_thread = await async_db.get(Thread, thread.id)
    assert db_thread is None

    await async_db.refresh(session)
    assert session.pending_thread_id is None


@pytest.mark.asyncio
async def test_delete_thread_with_pending_thread_id_does_not_crash(
    auth_client: AsyncClient, async_db: AsyncSession, test_username: str
) -> None:
    """Regression test for BUG-131: IntegrityError when deleting thread with pending_thread_id.

    This test verifies that deleting a thread that has sessions with pending_thread_id
    set does not cause a ForeignViolation error. The fix ensures that the UPDATE
    to clear pending_thread_id is flushed before the DELETE executes.
    """
    from datetime import UTC, datetime

    from app.models import Session as SessionModel, Thread, User

    result = await async_db.execute(select(User).where(User.username == test_username))
    user = result.scalar_one()
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    session = SessionModel(
        start_die=6,
        user_id=user.id,
        pending_thread_id=thread.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    assert session.pending_thread_id == thread.id

    response = await auth_client.delete(f"/api/threads/{thread.id}")

    assert response.status_code == 204, (
        f"Expected 204, got {response.status_code}: {response.text if hasattr(response, 'text') else ''}"
    )

    db_thread = await async_db.get(Thread, thread.id)
    assert db_thread is None

    await async_db.refresh(session)
    assert session.pending_thread_id is None


@pytest.mark.asyncio
async def test_set_pending_thread_updates_timestamp_and_clears_cache(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{id}/set-pending updates pending_thread_updated_at and clears caches."""
    from datetime import datetime, UTC
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)
    thread_title = thread.title
    thread_format = thread.format
    thread_issues_remaining = thread.issues_remaining
    thread_queue_position = thread.queue_position

    session = SessionModel(
        start_die=6,
        user_id=user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    old_pending_updated_at = session.pending_thread_updated_at

    response = await auth_client.post(f"/api/threads/{thread.id}/set-pending")

    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"] == thread.id
    assert data["title"] == thread_title
    assert data["format"] == thread_format
    assert data["issues_remaining"] == thread_issues_remaining
    assert data["queue_position"] == thread_queue_position
    assert data["result"] == 0
    assert data["die_size"] == 6

    await async_db.refresh(session)
    assert session.pending_thread_id == thread.id
    assert session.pending_thread_updated_at is not None
    if old_pending_updated_at:
        assert session.pending_thread_updated_at > old_pending_updated_at


@pytest.mark.asyncio
async def test_set_pending_thread_rejects_completed_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{id}/set-pending returns 400 for completed threads."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="completed",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(f"/api/threads/{thread.id}/set-pending")

    assert response.status_code == 400
    assert "not active" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_set_pending_thread_rejects_thread_with_no_issues(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{id}/set-pending returns 400 for threads with no issues remaining."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(f"/api/threads/{thread.id}/set-pending")

    assert response.status_code == 400
    assert "no issues" in response.json()["detail"].lower()
