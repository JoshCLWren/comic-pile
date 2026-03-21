"""Coverage gap tests for queue.py, dependencies.py, and session.py."""

from datetime import UTC, datetime
import pytest
from unittest.mock import patch
from sqlalchemy.exc import OperationalError

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Collection, Dependency, Event, Session as SessionModel, Thread, User
from comic_pile.dependencies import (
    detect_circular_dependency,
)
from comic_pile.queue import get_roll_pool
from comic_pile.session import get_or_create, get_current_die


@pytest.mark.asyncio
async def test_get_roll_pool_with_collection_id(async_db: AsyncSession, default_user: User) -> None:
    """Test get_roll_pool filters by collection_id when provided (queue.py:251)."""
    from datetime import UTC, datetime

    collection = Collection(name="Test Collection", user_id=default_user.id)
    async_db.add(collection)
    await async_db.flush()

    thread_in_collection = Thread(
        title="Thread in Collection",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        collection_id=collection.id,
        created_at=datetime.now(UTC),
    )

    thread_outside_collection = Thread(
        title="Thread Outside Collection",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        collection_id=None,
        created_at=datetime.now(UTC),
    )

    async_db.add_all([thread_in_collection, thread_outside_collection])
    await async_db.commit()

    pool_with_collection = await get_roll_pool(
        default_user.id, async_db, collection_id=collection.id
    )
    assert len(pool_with_collection) == 1
    assert pool_with_collection[0].id == thread_in_collection.id

    pool_without_collection = await get_roll_pool(default_user.id, async_db, collection_id=None)
    assert len(pool_without_collection) == 2


@pytest.mark.asyncio
async def test_detect_circular_dependency_with_multiple_dependencies(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test detect_circular_dependency handles multiple dependencies correctly (dependencies.py:161-165)."""
    source_thread = Thread(
        title="Source",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    middle_thread = Thread(
        title="Middle",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    target_thread = Thread(
        title="Target",
        format="Comic",
        issues_remaining=1,
        queue_position=3,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add_all([source_thread, middle_thread, target_thread])
    await async_db.flush()

    async_db.add_all(
        [
            Dependency(source_thread_id=source_thread.id, target_thread_id=middle_thread.id),
            Dependency(source_thread_id=middle_thread.id, target_thread_id=target_thread.id),
        ]
    )
    await async_db.commit()

    result = await detect_circular_dependency(
        source_thread.id, target_thread.id, "thread", async_db
    )
    assert result is False

    result_cycle = await detect_circular_dependency(
        target_thread.id, source_thread.id, "thread", async_db
    )
    assert result_cycle is True


@pytest.mark.asyncio
async def test_get_or_create_returns_existing_after_lock(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test get_or_create returns session found after acquiring lock (session.py:149)."""
    from sqlalchemy import delete

    await async_db.execute(delete(SessionModel))
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
async def test_get_or_create_deadlock_retry_succeeds(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test get_or_create retries on deadlock and succeeds (session.py:160-167)."""
    from sqlalchemy import delete

    await async_db.execute(delete(SessionModel))
    await async_db.commit()

    call_count = 0
    original_commit = async_db.commit

    async def mock_commit_with_deadlock(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OperationalError("deadlock detected", {}, Exception())
        return await original_commit(*args, **kwargs)

    with patch.object(async_db, "commit", side_effect=mock_commit_with_deadlock):
        result = await get_or_create(async_db, user_id=default_user.id)

    assert result is not None
    assert result.start_die == 6
    assert call_count == 2


@pytest.mark.asyncio
async def test_get_or_create_deadlock_max_retries_exceeded(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test get_or_create raises RuntimeError after max retries (session.py:171)."""
    from sqlalchemy import delete

    await async_db.execute(delete(SessionModel))
    await async_db.commit()

    async def mock_commit_always_deadlock(*args, **kwargs):
        raise OperationalError("deadlock detected", {}, Exception())

    with patch.object(async_db, "commit", side_effect=mock_commit_always_deadlock):
        with pytest.raises(RuntimeError, match="Failed to get_or_create session after 3 retries"):
            await get_or_create(async_db, user_id=default_user.id)


@pytest.mark.asyncio
async def test_get_current_die_with_die_after_event(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test get_current_die returns die_after from last event (session.py:202-203)."""
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=20,
    )
    async_db.add(event)
    await async_db.commit()

    current_die = await get_current_die(session.id, async_db)
    assert current_die == 20


@pytest.mark.asyncio
async def test_get_current_die_with_die_after_none(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test get_current_die handles die_after=None in event (session.py:203)."""
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=None,
    )
    async_db.add(event)
    await async_db.commit()

    current_die = await get_current_die(session.id, async_db)
    assert current_die == 6


@pytest.mark.asyncio
async def test_detect_circular_dependency_empty_graph(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test detect_circular_dependency with no dependencies returns False (dependencies.py:161-165)."""
    result = await detect_circular_dependency(1, 2, "thread", async_db)
    assert result is False
