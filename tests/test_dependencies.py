"""Tests for dependency blocking logic."""

from datetime import UTC, datetime

import pytest

from app.models import Dependency, Thread, User
from comic_pile.dependencies import (
    detect_circular_dependency,
    get_blocked_thread_ids,
    get_blocking_explanations,
    refresh_user_blocked_status,
)
from comic_pile.queue import get_roll_pool


@pytest.mark.asyncio
async def test_get_blocked_thread_ids_and_explanations(async_db):
    """Blocked set and explanations should reflect unsatisfied source thread."""
    user = User(username="dep_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    a = Thread(title="A", format="Comic", issues_remaining=1, queue_position=1, status="active", user_id=user.id)
    b = Thread(title="B", format="Comic", issues_remaining=1, queue_position=2, status="active", user_id=user.id)
    async_db.add_all([a, b])
    await async_db.flush()

    async_db.add(Dependency(source_thread_id=a.id, target_thread_id=b.id))
    await async_db.commit()

    blocked = await get_blocked_thread_ids(user.id, async_db)
    assert blocked == {b.id}

    reasons = await get_blocking_explanations(b.id, user.id, async_db)
    assert reasons
    assert "Blocked by A" in reasons[0]


@pytest.mark.asyncio
async def test_circular_dependency_detected(async_db):
    """Cycle detection should reject edges that close a directed cycle."""
    user = User(username="cycle_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    a = Thread(title="A", format="Comic", issues_remaining=1, queue_position=1, status="active", user_id=user.id)
    b = Thread(title="B", format="Comic", issues_remaining=1, queue_position=2, status="active", user_id=user.id)
    c = Thread(title="C", format="Comic", issues_remaining=1, queue_position=3, status="active", user_id=user.id)
    async_db.add_all([a, b, c])
    await async_db.flush()

    async_db.add_all([
        Dependency(source_thread_id=a.id, target_thread_id=b.id),
        Dependency(source_thread_id=b.id, target_thread_id=c.id),
    ])
    await async_db.commit()

    assert await detect_circular_dependency(c.id, a.id, async_db) is True
    assert await detect_circular_dependency(a.id, c.id, async_db) is False


@pytest.mark.asyncio
async def test_roll_pool_excludes_blocked_threads(async_db):
    """Roll pool should skip blocked threads and include them once unblocked."""
    user = User(username="roll_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    a = Thread(title="A", format="Comic", issues_remaining=1, queue_position=1, status="active", user_id=user.id)
    b = Thread(title="B", format="Comic", issues_remaining=1, queue_position=2, status="active", user_id=user.id)
    c = Thread(title="C", format="Comic", issues_remaining=1, queue_position=3, status="active", user_id=user.id)
    async_db.add_all([a, b, c])
    await async_db.flush()

    async_db.add(Dependency(source_thread_id=a.id, target_thread_id=b.id))
    await async_db.commit()

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    pool = await get_roll_pool(user.id, async_db)
    assert [t.id for t in pool] == [a.id, c.id]

    a.status = "completed"
    await async_db.commit()

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    pool_after = await get_roll_pool(user.id, async_db)
    assert [t.id for t in pool_after] == [a.id, b.id, c.id]
