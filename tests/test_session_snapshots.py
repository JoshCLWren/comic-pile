"""Tests for session snapshots and restore."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Snapshot, Thread, User
from app.models import ReadingSession
from comic_pile.reading_session import create_session_start_snapshot, get_or_create

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

    session = ReadingSession(start_die=6, user_id=default_user.id, manual_die=20)
    async_db.add(session)
    await async_db.commit()

    await create_session_start_snapshot(async_db, session)


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


