"""Tests for session snapshots and restore."""

from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Snapshot, Thread, User
from app.models import Session as SessionModel
from comic_pile.session import create_session_start_snapshot, get_or_create

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

    response = await auth_client.post(f"/api/v1/sessions/{session.id}/restore-session-start")
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

async def test_restore_session_start_no_snapshot(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test restoring session when no session start snapshot exists."""
    from app.models import Session as SessionModel

    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.post(f"/api/v1/sessions/{session.id}/restore-session-start")
    assert response.status_code == 404
    assert "No session start snapshot found" in response.json()["detail"]

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

    await auth_client.delete(f"/api/v1/threads/{thread2.id}")

    response = await auth_client.post(f"/api/v1/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200

    refreshed_thread1 = await async_db.get(Thread, thread1.id)
    assert refreshed_thread1 is not None
    assert refreshed_thread1.issues_remaining == 10

    restored_thread = await async_db.get(Thread, thread2.id)
    assert restored_thread is not None
    assert restored_thread.issues_remaining == 5

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

    await auth_client.delete(f"/api/v1/threads/{thread2.id}")

    await async_db.refresh(session)
    assert session.pending_thread_id is None

    response = await auth_client.post(f"/api/v1/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200

    restored_thread2 = await async_db.get(Thread, thread2.id)
    assert restored_thread2 is not None

async def test_restore_session_start_recomputes_blocked_status(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Restore should recompute denormalized blocked flags from dependencies.

    Verifies that restore-session-start calls refresh_user_blocked_status and
    corrects stale denormalized is_blocked flags. Creates a thread whose
    is_blocked is spuriously True (no actual active dep), and verifies that
    restore corrects it to False via refresh_user_blocked_status.
    """
    thread1 = Thread(
        title="Prereq",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Blocked",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    issue_t2 = Issue(thread_id=thread2.id, issue_number="1", position=1, status="unread")
    async_db.add(issue_t2)
    await async_db.flush()

    thread2.next_unread_issue_id = issue_t2.id
    await async_db.commit()

    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    await create_session_start_snapshot(async_db, session)

    # Corrupt is_blocked to True even though no dep exists.
    thread2.is_blocked = True
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200

    # refresh_user_blocked_status should correct the stale True → False (no active dep).
    await async_db.refresh(thread2)
    assert thread2.is_blocked is False

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

