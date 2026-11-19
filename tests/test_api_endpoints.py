"""API endpoint integration tests."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReadingSession, Thread, User
from app.services import thread_service
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_create_thread(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Test POST /api/v1/threads/ creates new thread."""
    thread_data = {
        "title": "Spider-Man",
        "format": "Comic",
        "issues_remaining": 12,
    }
    response = await auth_client.post("/api/v1/threads/", json=thread_data)
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
    """Test POST /api/v1/threads/ validates input."""
    # Empty title
    invalid_data = {
        "title": "",
        "format": "Comic",
        "issues_remaining": 12,
    }
    response = await auth_client.post("/api/v1/threads/", json=invalid_data)
    assert response.status_code == 422

    # Whitespace-only title
    whitespace_data = {
        "title": "  ",
        "format": "Comic",
        "issues_remaining": 12,
    }
    response = await auth_client.post("/api/v1/threads/", json=whitespace_data)
    assert response.status_code == 422

    # Tab-only title
    tab_data = {
        "title": "\t\t",
        "format": "Comic",
        "issues_remaining": 12,
    }
    response = await auth_client.post("/api/v1/threads/", json=tab_data)
    assert response.status_code == 422

    # Newline-only title
    newline_data = {
        "title": "\n\n",
        "format": "Comic",
        "issues_remaining": 12,
    }
    response = await auth_client.post("/api/v1/threads/", json=newline_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_threads(
    async_db: AsyncSession, default_user: User, sample_data: dict
) -> None:
    """The Queue collection projection returns active threads only (#2567)."""
    _ = sample_data
    page = await thread_service.list_queue_threads(
        async_db, default_user.id, search=None, sort="position", page_size=50, page_token=None
    )

    threads = page.threads
    assert len(threads) == 4
    assert threads[0].title == "Superman"
    assert threads[1].title == "Batman"
    assert threads[2].title == "Flash"
    assert threads[3].title == "Aquaman"
    assert all(thread.status == "active" for thread in threads)


@pytest.mark.asyncio
async def test_list_threads_search(
    async_db: AsyncSession, default_user: User, sample_data: dict
) -> None:
    """Queue search filters active threads by title (#2567)."""
    _ = sample_data

    page = await thread_service.list_queue_threads(
        async_db, default_user.id, search="man", sort="position", page_size=50, page_token=None
    )
    titles = {thread.title for thread in page.threads}
    # Wonder Woman is completed, so it must not leak into active Queue search.
    assert titles == {"Superman", "Batman", "Aquaman"}


@pytest.mark.asyncio
async def test_list_threads_empty(async_db: AsyncSession) -> None:
    """An empty Queue collection returns no rows and no cursor."""
    user = await get_or_create_user_async(async_db, username="empty_queue_reader")
    page = await thread_service.list_queue_threads(
        async_db, user.id, search=None, sort="position", page_size=50, page_token=None
    )
    assert page.threads == []
    assert page.next_page_token is None
    assert page.active_count == 0


@pytest.mark.asyncio
async def test_completed_threads_json_is_v1_only(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """New client resources must not gain a bare /api/* twin (versioning)."""
    _ = sample_data
    response = await auth_client.get("/api/threads/completed/threads")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_thread(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Test PUT /api/v1/threads/{id} updates thread."""
    _ = sample_data
    update_data = {
        "title": "Superman Updated",
        "format": "Trade Paperback",
        "issues_remaining": 8,
    }
    response = await auth_client.put("/api/v1/threads/1", json=update_data)
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
    """Test PUT /api/v1/threads/{id} with partial data."""
    _ = sample_data
    update_data = {
        "title": "Batman Updated",
    }
    response = await auth_client.put("/api/v1/threads/2", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["title"] == "Batman Updated"
    assert thread["format"] == "Comic"
    assert thread["issues_remaining"] == 5


@pytest.mark.asyncio
async def test_update_thread_validation(auth_client: AsyncClient, sample_data: dict) -> None:
    """Test PUT /api/v1/threads/{id} validates input."""
    _ = sample_data

    # Whitespace-only title
    whitespace_data = {
        "title": "  ",
    }
    response = await auth_client.put("/api/v1/threads/1", json=whitespace_data)
    assert response.status_code == 422

    # Tab-only title
    tab_data = {
        "title": "\t\t",
    }
    response = await auth_client.put("/api/v1/threads/1", json=tab_data)
    assert response.status_code == 422

    # Newline-only title
    newline_data = {
        "title": "\n\n",
    }
    response = await auth_client.put("/api/v1/threads/1", json=newline_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_thread_not_found(auth_client: AsyncClient) -> None:
    """Test PUT /api/v1/threads/{id} returns 404 for non-existent thread."""
    update_data = {
        "title": "Non-existent",
    }
    response = await auth_client.put("/api/v1/threads/999", json=update_data)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_thread_complete_status(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Test PUT /api/v1/threads/{id} sets completed status when issues_remaining is 0."""
    _ = sample_data
    update_data = {
        "issues_remaining": 0,
    }
    response = await auth_client.put("/api/v1/threads/1", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["status"] == "completed"
    assert thread["issues_remaining"] == 0
    assert thread["queue_position"] == 0

    from app.models import Thread

    db_thread = await async_db.get(Thread, 1)
    assert db_thread is not None
    assert db_thread.status == "completed"


@pytest.mark.asyncio
async def test_update_thread_active_status(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Test PUT /api/v1/threads/{id} sets active status when issues_remaining > 0."""
    _ = sample_data
    update_data = {
        "issues_remaining": 5,
    }
    response = await auth_client.put("/api/v1/threads/3", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["status"] == "active"
    assert thread["issues_remaining"] == 5

    from app.models import Thread

    db_thread = await async_db.get(Thread, 3)
    assert db_thread is not None
    assert db_thread.status == "active"


@pytest.mark.asyncio
async def test_update_thread_performance_issue_tracking(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that update_thread correctly handles issue-tracking threads.

    Verifies that for migrated threads (total_issues set), the response includes
    issues_remaining and next_unread_issue_number without extra per-thread DB
    queries (issue #3442). The fix pre-fetches these values before calling
    thread_to_response to avoid additional round-trips.
    """
    from app.models import Issue, Thread

    now = datetime.now(UTC)

    # Create a thread with issue tracking enabled
    thread = Thread(
        title="Perf Test Thread",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        total_issues=5,
        reading_progress="in_progress",
        last_activity_at=now,
    )
    async_db.add(thread)
    await async_db.flush()

    # Create issue records
    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=str(i),
            position=i,
            status="unread" if i > 1 else "read",
            read_at=now if i <= 1 else None,
        )
        for i in range(1, 6)
    ]
    async_db.add_all(issues)
    await async_db.flush()

    # Set next_unread_issue_id to the first unread issue
    thread.next_unread_issue_id = issues[1].id  # issue #2 is unread
    await async_db.flush()

    # Update the thread
    update_data = {"title": "Perf Test Thread Updated"}
    response = await auth_client.put(
        f"/api/v1/threads/{thread.id}", json=update_data
    )
    assert response.status_code == 200

    data = response.json()
    assert data["title"] == "Perf Test Thread Updated"
    assert data["issues_remaining"] == 4
    assert data["status"] == "active"
    assert data["queue_position"] == 1
    assert data["total_issues"] == 5
    assert "next_unread_issue_number" in data
    assert data["next_unread_issue_number"] == "2"  # issue #2's number

    # Verify DB thread state
    db_thread = await async_db.get(Thread, thread.id)
    assert db_thread is not None
    assert db_thread.title == "Perf Test Thread Updated"
    assert db_thread.total_issues == 5
    assert db_thread.issues_remaining == 3


@pytest.mark.asyncio
async def test_delete_thread(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Test DELETE /api/v1/threads/{id} removes thread."""
    _ = sample_data
    response = await auth_client.delete("/api/v1/threads/1")
    assert response.status_code == 204

    from app.models import Thread

    db_thread = await async_db.get(Thread, 1)
    assert db_thread is None


@pytest.mark.asyncio
async def test_delete_thread_not_found(auth_client: AsyncClient) -> None:
    """Test DELETE /api/v1/threads/{id} returns 404 for non-existent thread."""
    response = await auth_client.delete("/api/v1/threads/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_thread_cascades_to_events_and_snapshots(
    sample_data: dict, async_db: AsyncSession, auth_client: AsyncClient
) -> None:
    """Test that deleting a thread also deletes associated events and snapshots."""
    _ = sample_data
    from datetime import UTC, datetime

    from app.models import Event, ReadingSession, Snapshot, Thread

    now = datetime.now(UTC)
    user = sample_data["user"]
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

    session = ReadingSession(start_die=6, user_id=user_id, started_at=now)
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

    response = await auth_client.delete(f"/api/v1/threads/{thread_id}")
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
async def test_list_threads_includes_notes(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession, test_username: str
) -> None:
    """Test GET /api/v1/threads/ includes notes field in all threads."""
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

    page = await thread_service.list_queue_threads(
        async_db, user.id, search=None, sort="position", page_size=50, page_token=None
    )
    threads = page.threads
    assert len(threads) >= 2

    flash_thread = next((t for t in threads if t.title == "Flash"), None)
    aquaman_thread = next((t for t in threads if t.title == "Aquaman"), None)

    assert flash_thread is not None
    assert flash_thread.notes == "Fast-paced storytelling"

    assert aquaman_thread is not None
    assert aquaman_thread.notes is None


@pytest.mark.asyncio
async def test_delete_thread_clears_pending_thread_id(
    auth_client: AsyncClient, async_db: AsyncSession, test_username: str
) -> None:
    """Test that deleting a thread clears pending_thread_id from sessions."""
    from datetime import UTC, datetime

    from app.models import ReadingSession, Thread, User

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

    session = ReadingSession(
        start_die=6, user_id=user.id, pending_thread_id=thread.id, started_at=datetime.now(UTC)
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    assert session.pending_thread_id == thread.id

    response = await auth_client.delete(f"/api/v1/threads/{thread.id}")

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

    from app.models import ReadingSession, Thread, User

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

    session = ReadingSession(
        start_die=6,
        user_id=user.id,
        pending_thread_id=thread.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    assert session.pending_thread_id == thread.id

    response = await auth_client.delete(f"/api/v1/threads/{thread.id}")

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

    session = ReadingSession(
        start_die=6,
        user_id=user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    old_pending_updated_at = session.pending_thread_updated_at

    response = await auth_client.post(f"/api/v1/threads/{thread.id}/set-pending")

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

    response = await auth_client.post(f"/api/v1/threads/{thread.id}/set-pending")

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

    response = await auth_client.post(f"/api/v1/threads/{thread.id}/set-pending")

    assert response.status_code == 400
    assert "no issues" in response.json()["detail"].lower()
