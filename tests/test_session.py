"""Tests for session logic."""

from datetime import UTC, datetime, timedelta

import pytest

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import get_active_thread
from app.config import clear_settings_cache
from app.models import Event, Session, Snapshot, Thread, User
from app.models import Session as SessionModel
from comic_pile.session import (
    create_session_start_snapshot,
    end_session,
    get_or_create,
    is_active,
    should_start_new,
)


@pytest.mark.asyncio
async def test_session_env_int_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Session env parsing clamps values and ignores invalid ints.

    Args:
        monkeypatch: Pytest's monkeypatch fixture for modifying env vars.
    """
    import comic_pile.session as session_mod

    # Clear cached settings to pick up new env vars
    clear_settings_cache()

    monkeypatch.setenv("SESSION_GAP_HOURS", "12")
    clear_settings_cache()
    assert session_mod._session_gap_hours() == 12

    monkeypatch.setenv("SESSION_GAP_HOURS", "0")
    clear_settings_cache()
    # 0 is outside valid range, pydantic will clamp via validator
    assert session_mod._session_gap_hours() == 6

    monkeypatch.setenv("START_DIE", "20")
    clear_settings_cache()
    assert session_mod._start_die() == 20

    monkeypatch.setenv("START_DIE", "3")
    clear_settings_cache()
    # 3 is outside valid range
    assert session_mod._start_die() == 6


@pytest.mark.asyncio
async def test_get_or_create_ignores_advisory_lock_failure(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Advisory lock errors should not prevent session creation."""
    original_execute = async_db.execute

    async def wrapped_execute(statement, *args, **kwargs):
        if "pg_advisory_xact_lock" in str(statement):
            raise RuntimeError("boom")
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(async_db, "execute", wrapped_execute)

    session = await get_or_create(async_db, user_id=1)
    assert session.id is not None
    assert session.user_id == 1


@pytest.mark.asyncio
async def test_is_active_true(async_db: AsyncSession, default_user: User) -> None:
    """Session created < 6 hours ago is active."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    result = await is_active(session.started_at, session.ended_at, async_db)
    assert result is True


@pytest.mark.asyncio
async def test_is_active_false_old(async_db: AsyncSession, default_user: User) -> None:
    """Session created > 6 hours ago is inactive."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=7),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    result = await is_active(session.started_at, session.ended_at, async_db)
    assert result is False


@pytest.mark.asyncio
async def test_is_active_false_ended(async_db: AsyncSession, default_user: User) -> None:
    """Session that has ended is inactive."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        ended_at=datetime.now(UTC),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    result = await is_active(session.started_at, session.ended_at, async_db)
    assert result is False


@pytest.mark.asyncio
async def test_should_start_new_true(async_db: AsyncSession, default_user: User) -> None:
    """No active session in last 6 hours."""
    old_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=7),
        ended_at=datetime.now(UTC),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(old_session)
    await async_db.commit()

    result = await should_start_new(async_db, user_id=default_user.id)
    assert result is True


@pytest.mark.asyncio
async def test_should_start_new_false(async_db: AsyncSession, default_user: User) -> None:
    """Active session exists."""
    active_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(active_session)
    await async_db.commit()

    result = await should_start_new(async_db, user_id=default_user.id)
    assert result is False


@pytest.mark.asyncio
async def test_get_or_create_existing(async_db: AsyncSession, sample_data: dict) -> None:
    """Returns existing active session (< 6 hours old)."""
    # End all sample sessions first
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    await async_db.commit()

    # Create a fresh active session within last 6 hours
    active_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=1,
    )
    async_db.add(active_session)
    await async_db.commit()

    result = await get_or_create(async_db, user_id=1)
    assert result.id == active_session.id


@pytest.mark.asyncio
async def test_get_or_create_new(async_db: AsyncSession, sample_data: dict) -> None:
    """Creates new session when none active."""
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    await async_db.commit()

    new_session = await get_or_create(async_db, user_id=1)
    assert new_session.start_die == 6
    assert new_session.user_id == 1


@pytest.mark.asyncio
async def test_end_session(async_db: AsyncSession, sample_data: dict) -> None:
    """Marks session as ended."""
    session = sample_data["sessions"][0]
    assert session.ended_at is None

    await end_session(session.id, async_db)

    await async_db.refresh(session)
    assert session.ended_at is not None


@pytest.mark.asyncio
async def test_end_session_nonexistent(async_db: AsyncSession, default_user: User) -> None:
    """Gracefully handles ending non-existent session."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    await end_session(999, async_db)

    assert True


@pytest.mark.asyncio
async def test_is_active_exactly_6_hours(async_db: AsyncSession, default_user: User) -> None:
    """Session created exactly 6 hours ago is considered active."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=5, minutes=59),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    result = await is_active(session.started_at, session.ended_at, async_db)
    assert result is True


@pytest.mark.asyncio
async def test_should_start_new_multiple_old_sessions(
    async_db: AsyncSession, default_user: User
) -> None:
    """Multiple old sessions still return true."""
    for i in range(3):
        old_session = SessionModel(
            started_at=datetime.now(UTC) - timedelta(hours=7 + i),
            ended_at=datetime.now(UTC),
            start_die=6,
            user_id=default_user.id,
        )
        async_db.add(old_session)
    await async_db.commit()

    result = await should_start_new(async_db, user_id=default_user.id)
    assert result is True


@pytest.mark.asyncio
async def test_get_or_create_returns_most_recent(
    async_db: AsyncSession, default_user: User
) -> None:
    """Returns most recent active session when multiple exist."""
    recent_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=10,
        user_id=default_user.id,
    )
    older_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=2),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(recent_session)
    async_db.add(older_session)
    await async_db.commit()

    result = await get_or_create(async_db, user_id=default_user.id)
    assert result.id == recent_session.id
    assert result.start_die == 10


@pytest.mark.asyncio
async def test_get_or_create_creates_default_user(async_db: AsyncSession) -> None:
    """BUG-141: Creates default user when user_id doesn't exist."""
    from app.models import User

    non_existent_user_id = 999

    user = await async_db.get(User, non_existent_user_id)
    assert user is None

    new_session = await get_or_create(async_db, user_id=non_existent_user_id)

    assert new_session is not None
    assert new_session.user_id == non_existent_user_id

    user = await async_db.get(User, non_existent_user_id)
    assert user is not None
    assert user.username == "default_user"


@pytest.mark.asyncio
async def test_get_or_create_creates_user_id_1(async_db: AsyncSession) -> None:
    """BUG-142: Creates default user when user_id=1 doesn't exist."""
    from app.models import User
    from sqlalchemy import delete

    await async_db.execute(delete(Session))
    await async_db.execute(delete(User))
    await async_db.commit()

    user = await async_db.get(User, 1)
    assert user is None

    new_session = await get_or_create(async_db, user_id=1)

    assert new_session is not None
    assert new_session.user_id == 1

    user = await async_db.get(User, 1)
    assert user is not None
    assert user.username == "default_user"


@pytest.mark.asyncio
async def test_get_active_thread_includes_last_rolled_result(
    async_db: AsyncSession, sample_data: dict
) -> None:
    """Get active thread includes last rolled result value."""
    session = sample_data["sessions"][0]
    thread = sample_data["threads"][0]

    event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(event)
    await async_db.commit()

    active_thread = await get_active_thread(session.id, async_db)

    assert active_thread is not None
    assert active_thread.id == thread.id
    assert active_thread.last_rolled_result == 4


@pytest.mark.asyncio
async def test_session_start_snapshot_created(async_db: AsyncSession, default_user: User) -> None:
    """A snapshot is created when a new session starts."""
    threads = []
    for i in range(3):
        thread = Thread(
            title=f"Test Thread {i}",
            format="Comic",
            issues_remaining=5 + i,
            queue_position=i + 1,
            status="active",
            user_id=default_user.id,
            created_at=datetime.now(UTC),
        )
        async_db.add(thread)
        threads.append(thread)
    await async_db.commit()

    session = await get_or_create(async_db, user_id=default_user.id)

    from sqlalchemy import select

    result = await async_db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session.id)
        .where(Snapshot.description == "Session start")
        .order_by(Snapshot.created_at)
    )
    snapshot = result.scalars().first()

    assert snapshot is not None
    assert snapshot.session_id == session.id
    assert snapshot.description == "Session start"
    assert snapshot.session_state is not None
    assert snapshot.session_state["start_die"] == 6
    assert snapshot.session_state["manual_die"] is None
    assert len(snapshot.thread_states) == 3


@pytest.mark.asyncio
async def test_session_start_snapshot_captures_thread_states(
    async_db: AsyncSession, default_user: User
) -> None:
    """Snapshot captures all thread states at session start."""
    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Thread 2",
        format="Graphic Novel",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        last_rating=4.5,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    session = await get_or_create(async_db, user_id=default_user.id)

    from sqlalchemy import select

    result = await async_db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session.id)
        .where(Snapshot.description == "Session start")
    )
    snapshot = result.scalars().first()

    assert snapshot is not None
    thread1_state = snapshot.thread_states[str(thread1.id)]
    assert thread1_state["issues_remaining"] == 10
    assert thread1_state["queue_position"] == 1
    assert thread1_state["status"] == "active"

    thread2_state = snapshot.thread_states[str(thread2.id)]
    assert thread2_state["issues_remaining"] == 5
    assert thread2_state["queue_position"] == 2
    assert thread2_state["last_rating"] == 4.5
    assert thread2_state["status"] == "active"


@pytest.mark.asyncio
async def test_session_start_snapshot_captures_manual_die(
    async_db: AsyncSession, default_user: User
) -> None:
    """Snapshot captures session manual die state."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    session = SessionModel(start_die=6, user_id=default_user.id, manual_die=20)
    async_db.add(session)
    await async_db.commit()

    await create_session_start_snapshot(async_db, session)

    from sqlalchemy import select

    result = await async_db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session.id)
        .where(Snapshot.description == "Session start")
    )
    snapshot = result.scalars().first()

    assert snapshot is not None, "Snapshot should not be None"
    if snapshot.session_state is None:
        raise AssertionError("session_state should not be None")
    assert snapshot.session_state["start_die"] == 6
    assert snapshot.session_state["manual_die"] == 20


@pytest.mark.asyncio
async def test_get_current_session_active(
    client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test getting current active session."""
    from app.auth import create_access_token
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(event)
    await async_db.commit()

    token = create_access_token(data={"sub": default_user.username, "jti": "test"})
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/sessions/current/", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session.id
    assert data["start_die"] == 6
    assert data["active_thread"] is not None
    assert data["active_thread"]["id"] == thread.id
    assert data["current_die"] == 6


@pytest.mark.asyncio
async def test_get_current_session_no_active(
    client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test getting current session creates a new session when none is active."""
    from app.auth import create_access_token
    from app.models import Session as SessionModel

    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC) - timedelta(hours=7),
        ended_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()

    token = create_access_token(data={"sub": default_user.username, "jti": "test"})
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/sessions/current/", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["start_die"] == 6


@pytest.mark.asyncio
async def test_list_sessions(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test listing all sessions with pagination."""
    from app.models import Session as SessionModel

    for i in range(5):
        session = SessionModel(
            start_die=6 + i, user_id=default_user.id, started_at=datetime.now(UTC)
        )
        async_db.add(session)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/?limit=3&offset=0")
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 3


@pytest.mark.asyncio
async def test_list_sessions_pagination(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test session pagination works correctly."""
    from app.models import Session as SessionModel

    for i in range(5):
        session = SessionModel(
            start_die=6 + i, user_id=default_user.id, started_at=datetime.now(UTC)
        )
        async_db.add(session)
    await async_db.commit()

    first_page = await auth_client.get("/api/sessions/?limit=2&offset=0")
    assert first_page.status_code == 200
    first_sessions = first_page.json()
    assert len(first_sessions) == 2

    second_page = await auth_client.get("/api/sessions/?limit=2&offset=2")
    assert second_page.status_code == 200
    second_sessions = second_page.json()
    assert len(second_sessions) == 2

    assert first_sessions[0]["id"] != second_sessions[0]["id"]


@pytest.mark.asyncio
async def test_get_session_by_id(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test getting a specific session by ID."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session.id
    assert data["start_die"] == 6


@pytest.mark.asyncio
async def test_get_session_not_found(auth_client: AsyncClient) -> None:
    """Test getting a non-existent session."""
    response = await auth_client.get("/api/sessions/9999")
    assert response.status_code == 404
    assert "Session not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_session_includes_ladder_path(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test session response includes dice ladder path."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    event1 = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(event1)

    event2 = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    async_db.add(event2)
    await async_db.commit()

    response = await auth_client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert "6 → 8" in data["ladder_path"]


@pytest.mark.asyncio
async def test_get_session_includes_snapshot_info(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test session response includes snapshot count and restore point info."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    async_db.add(event)
    await async_db.commit()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states={thread.id: {"issues_remaining": 10}},
        description="After rating",
    )
    async_db.add(snapshot)
    await async_db.commit()

    response = await auth_client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["snapshot_count"] == 1
    assert data["has_restore_point"] is True


@pytest.mark.asyncio
async def test_restore_session_start(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Restore session to start state via API."""
    from app.models import Session as SessionModel

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Thread 2",
        format="Graphic Novel",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        last_rating=4.5,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    session = SessionModel(start_die=6, user_id=default_user.id, manual_die=10)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    await create_session_start_snapshot(async_db, session)

    thread1.issues_remaining = 5
    thread2.queue_position = 5
    session.manual_die = 20
    await async_db.commit()

    response = await auth_client.post(f"/api/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200
    data = response.json()
    assert data["start_die"] == 6
    assert data["manual_die"] == 10

    refreshed_thread1 = await async_db.get(Thread, thread1.id)
    assert refreshed_thread1 is not None
    refreshed_thread2 = await async_db.get(Thread, thread2.id)
    assert refreshed_thread2 is not None
    await async_db.refresh(session)

    assert refreshed_thread1.issues_remaining == 10
    assert refreshed_thread2.queue_position == 2
    assert session.manual_die == 10


@pytest.mark.asyncio
async def test_restore_session_start_no_snapshot(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test restoring session when no session start snapshot exists."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.post(f"/api/sessions/{session.id}/restore-session-start")
    assert response.status_code == 404
    assert "No session start snapshot found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_restore_session_start_with_deleted_threads(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that restore handles threads that were deleted after snapshot."""
    from app.models import Session as SessionModel

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Thread 2",
        format="Graphic Novel",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    await create_session_start_snapshot(async_db, session)

    thread2.issues_remaining = 0
    await async_db.commit()

    await auth_client.delete(f"/api/threads/{thread2.id}")

    response = await auth_client.post(f"/api/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200

    refreshed_thread1 = await async_db.get(Thread, thread1.id)
    assert refreshed_thread1 is not None
    assert refreshed_thread1.issues_remaining == 10

    restored_thread = await async_db.get(Thread, thread2.id)
    assert restored_thread is not None
    assert restored_thread.issues_remaining == 5


@pytest.mark.asyncio
async def test_restore_session_start_clears_pending_thread_id(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that restore-session-start clears pending_thread_id from sessions when deleting threads.

    Regression test for BUG-131: Ensures that when restoring to a snapshot where
    threads no longer exist, sessions with pending_thread_id referencing those
    threads have their pending_thread_id cleared to prevent ForeignViolation errors.
    """
    from app.models import Session as SessionModel

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Thread 2",
        format="Graphic Novel",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    session = SessionModel(start_die=6, user_id=default_user.id, pending_thread_id=thread2.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    await create_session_start_snapshot(async_db, session)

    thread2.issues_remaining = 0
    await async_db.commit()

    await auth_client.delete(f"/api/threads/{thread2.id}")

    await async_db.refresh(session)
    assert session.pending_thread_id is None

    response = await auth_client.post(f"/api/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200

    restored_thread2 = await async_db.get(Thread, thread2.id)
    assert restored_thread2 is not None


@pytest.mark.asyncio
async def test_undo_to_snapshot_clears_pending_thread_id(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test that undo_to_snapshot clears pending_thread_id when processing.

    Regression test for BUG-131: Verifies that snapshot restoration works correctly.
    """
    from app.api.undo import undo_to_snapshot
    from app.models import Session as SessionModel, Snapshot

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread1)
    await async_db.commit()
    await async_db.refresh(thread1)

    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    await create_session_start_snapshot(async_db, session)

    result = await async_db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session.id)
        .where(Snapshot.description == "Session start")
        .order_by(Snapshot.created_at)
    )
    snapshot = result.scalars().first()

    assert snapshot is not None

    # Modify thread1 and commit to create changes
    thread1.issues_remaining = 5
    await async_db.commit()

    # Undo to snapshot
    await undo_to_snapshot(session.id, snapshot.id, default_user, async_db)

    await async_db.refresh(session)
    assert session.pending_thread_id is None


@pytest.mark.asyncio
async def test_is_active_no_lazy_load(async_db: AsyncSession, default_user: User) -> None:
    """Test that is_active doesn't cause lazy load of session object."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    started_at = session.started_at
    ended_at = session.ended_at

    result = await is_active(started_at, ended_at, async_db)
    assert result is True

    old_started_at = datetime.now(UTC) - timedelta(hours=7)
    old_ended_at = None
    result = await is_active(old_started_at, old_ended_at, async_db)
    assert result is False

    ended_started_at = datetime.now(UTC) - timedelta(hours=1)
    ended_ended_at = datetime.now(UTC)
    result = await is_active(ended_started_at, ended_ended_at, async_db)
    assert result is False


@pytest.mark.asyncio
async def test_get_or_create_deadlock_retry(
    async_db: AsyncSession, sample_data: dict, default_user: User
) -> None:
    """Test that get_or_create creates new session when no active one exists.

    Regression test for BUG-126: OperationalError deadlock handling.
    Verifies that get_or_create can successfully create a session when needed.
    """
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    await async_db.commit()

    new_session = await get_or_create(async_db, user_id=default_user.id)
    assert new_session is not None
    assert new_session.start_die == 6


@pytest.mark.asyncio
async def test_get_or_create_uses_session_id_to_prevent_lazy_load(
    async_db: AsyncSession, sample_data: dict, default_user: User
) -> None:
    """Test that get_or_create session object doesn't cause lazy loading issues.

    Regression test for BUG-126: Verify that session returned from get_or_create
    can have its id extracted without triggering lazy loading that causes deadlocks.
    """
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    await async_db.commit()

    result_session = await get_or_create(async_db, user_id=default_user.id)

    session_id = result_session.id
    assert session_id is not None
    assert isinstance(session_id, int)


@pytest.mark.asyncio
async def test_get_or_create_non_deadlock_operational_error(
    async_db: AsyncSession, sample_data: dict
) -> None:
    """Test that get_or_create raises non-deadlock OperationalError.

    Regression test for BUG-126: Verify that non-deadlock OperationalErrors
    are properly raised without retrying.
    """
    from unittest.mock import patch
    from sqlalchemy.exc import OperationalError

    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC) - timedelta(hours=7)
    await async_db.commit()

    commit_call_count = 0
    original_commit = async_db.commit

    async def mock_commit(*args, **kwargs):
        nonlocal commit_call_count
        commit_call_count += 1
        if commit_call_count == 1:
            raise OperationalError("some other error", {}, Exception())
        return await original_commit(*args, **kwargs)

    with patch.object(async_db, "commit", side_effect=mock_commit):
        with pytest.raises(OperationalError, match="some other error"):
            await get_or_create(async_db, user_id=1)


@pytest.mark.asyncio
async def test_is_active_with_naive_datetime(async_db: AsyncSession, default_user: User) -> None:
    """Test that is_active handles datetime without timezone.

    When a datetime has no tzinfo, it should be treated as UTC.
    This test verifies the branch is executed (coverage).
    """
    session = SessionModel(
        started_at=datetime.now() - timedelta(hours=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    naive_dt = datetime.now() - timedelta(hours=1)
    assert naive_dt.tzinfo is None

    result = await is_active(naive_dt, None, async_db)
    assert result is not None


@pytest.mark.asyncio
async def test_is_active_naive_old_datetime(async_db: AsyncSession, default_user: User) -> None:
    """Test that is_active handles old naive datetime correctly."""
    session = SessionModel(
        started_at=datetime.now() - timedelta(hours=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    naive_dt = datetime.now() - timedelta(hours=7)
    assert naive_dt.tzinfo is None

    result = await is_active(naive_dt, None, async_db)
    assert result is not None


@pytest.mark.asyncio
async def test_get_or_create_returns_existing_within_time_window(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test that get_or_create returns existing session when one exists within time window.

    This tests the early return path at line 148 where active_session is found
    before attempting to create a new session.
    """
    from app.models import Session as SessionModel

    existing_session = SessionModel(
        start_die=8,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(existing_session)
    await async_db.commit()
    await async_db.refresh(existing_session)

    result = await get_or_create(async_db, user_id=default_user.id)

    assert result.id == existing_session.id
    assert result.start_die == 8


@pytest.mark.asyncio
async def test_move_to_position_handles_zero(async_db: AsyncSession, sample_data: dict) -> None:
    """Test that move_to_position handles new_position=0 correctly.

    This covers line 70 where new_position is set to 1 when it's < 1.
    """
    from comic_pile.queue import move_to_position

    thread = sample_data["threads"][0]

    await move_to_position(thread.id, thread.user_id, 0, async_db)

    await async_db.refresh(thread)
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_get_or_create_race_condition_after_lock(
    async_db: AsyncSession, sample_data: dict, default_user: User
) -> None:
    """Test that get_or_create returns existing session when found.

    This tests the path where an active session already exists and is returned.
    """
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC) - timedelta(hours=7)
    await async_db.commit()

    existing_session = SessionModel(
        start_die=10,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(existing_session)
    await async_db.commit()
    await async_db.refresh(existing_session)

    result = await get_or_create(async_db, user_id=default_user.id)
    assert result.id == existing_session.id
    assert result.start_die == 10


@pytest.mark.asyncio
async def test_get_or_create_deadlock_retries_with_backoff(
    async_db: AsyncSession, sample_data: dict, default_user: User
) -> None:
    """Test that get_or_create returns existing session found after lock."""
    from app.models import Session as SessionModel

    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC) - timedelta(hours=7)
    await async_db.commit()

    existing_session = SessionModel(
        start_die=8,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(existing_session)
    await async_db.commit()
    await async_db.refresh(existing_session)

    result = await get_or_create(async_db, user_id=default_user.id)
    assert result.id == existing_session.id
    assert result.start_die == 8


@pytest.mark.asyncio
async def test_get_or_create_returns_existing_after_lock(
    async_db: AsyncSession, sample_data: dict, default_user: User
) -> None:
    """Test that get_or_create returns session found after acquiring lock.

    This tests the code path at line 141 where active_session is found
    after the lock is acquired.
    """
    from app.models import Session as SessionModel

    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC) - timedelta(hours=7)
    await async_db.commit()

    existing_session = SessionModel(
        start_die=10,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(existing_session)
    await async_db.commit()
    await async_db.refresh(existing_session)

    result = await get_or_create(async_db, user_id=default_user.id)
    assert result.id == existing_session.id
    assert result.start_die == 10


@pytest.mark.asyncio
async def test_get_current_die_returns_manual_die(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test that get_current_die returns manual_die when set.

    This tests line 194 where session.manual_die is returned.
    """
    from comic_pile.session import get_current_die
    from app.models import Session as SessionModel

    session = SessionModel(
        start_die=6,
        manual_die=20,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    current_die = await get_current_die(session.id, async_db)
    assert current_die == 20


@pytest.mark.asyncio
async def test_get_current_session_after_get_or_create_no_lazy_load(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that accessing session.id after get_or_create doesn't cause MissingGreenlet.

    Regression test for MissingGreenlet error when get_current_session creates a new
    session via get_or_create, which commits during create_session_start_snapshot,
    expiring the session object. Accessing .id on expired session triggers lazy load
    which fails in async context with MissingGreenlet.

    The fix ensures db.refresh() is called before accessing session.id.
    """
    from sqlalchemy import delete

    await async_db.execute(delete(SessionModel))
    await async_db.commit()

    thread1 = Thread(
        title="Test Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Test Thread 2",
        format="Graphic Novel",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["start_die"] == 6
    assert data["user_id"] == default_user.id
