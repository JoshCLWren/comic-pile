"""Tests for dependency blocking logic."""

from datetime import UTC, datetime

import pytest

from app.models import Dependency, Issue, Thread, User
from sqlalchemy import text
from comic_pile.dependencies import (
    detect_circular_dependency,
    get_blocked_thread_ids,
    get_blocking_explanations,
    refresh_user_blocked_status,
    update_thread_blocked_status,
    validate_position_dependency_consistency,
)
from comic_pile.queue import get_roll_pool


@pytest.mark.asyncio
async def test_get_blocked_thread_ids_and_explanations(async_db):
    """Blocked set and explanations should reflect unsatisfied source thread."""
    user = User(username="dep_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()
    # Ensure the SQL sequence for users.id is in sync with the current max(id)
    # to avoid UniqueViolationError when autoincrement assigns the next id
    # in environments where tests are run in a shared/test database fixture.
    await async_db.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('users','id'), COALESCE((SELECT MAX(id) FROM users), 1), true)"
        )
    )

    a = Thread(
        title="A",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    b = Thread(
        title="B",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
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

    a = Thread(
        title="A",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    b = Thread(
        title="B",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    c = Thread(
        title="C",
        format="Comic",
        issues_remaining=1,
        queue_position=3,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([a, b, c])
    await async_db.flush()

    async_db.add_all(
        [
            Dependency(source_thread_id=a.id, target_thread_id=b.id),
            Dependency(source_thread_id=b.id, target_thread_id=c.id),
        ]
    )
    await async_db.commit()

    assert await detect_circular_dependency(c.id, a.id, "thread", async_db) is True
    assert await detect_circular_dependency(a.id, c.id, "thread", async_db) is False


@pytest.mark.asyncio
async def test_roll_pool_excludes_blocked_threads(async_db):
    """Roll pool should skip blocked threads and include them once unblocked."""
    user = User(username="roll_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    a = Thread(
        title="A",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    b = Thread(
        title="B",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    c = Thread(
        title="C",
        format="Comic",
        issues_remaining=1,
        queue_position=3,
        status="active",
        user_id=user.id,
    )
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
    assert [t.id for t in pool_after] == [b.id, c.id]


@pytest.mark.asyncio
async def test_circular_dependency_detects_self_reference(async_db):
    """Self-dependency should always be treated as circular."""
    assert await detect_circular_dependency(123, 123, "thread", async_db) is True


@pytest.mark.asyncio
async def test_circular_dependency_invalid_dependency_type(async_db):
    """Invalid dependency type should return False (not circular)."""
    assert await detect_circular_dependency(1, 2, "invalid_type", async_db) is False


@pytest.mark.asyncio
async def test_circular_dependency_handles_revisited_nodes(async_db):
    """Graph traversal should safely handle revisiting the same node."""
    user = User(username="revisit_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    t1 = Thread(
        title="T1",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    t2 = Thread(
        title="T2",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    t3 = Thread(
        title="T3",
        format="Comic",
        issues_remaining=1,
        queue_position=3,
        status="active",
        user_id=user.id,
    )
    t4 = Thread(
        title="T4",
        format="Comic",
        issues_remaining=1,
        queue_position=4,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([t1, t2, t3, t4])
    await async_db.flush()

    async_db.add_all(
        [
            Dependency(source_thread_id=t1.id, target_thread_id=t2.id),
            Dependency(source_thread_id=t1.id, target_thread_id=t3.id),
            Dependency(source_thread_id=t2.id, target_thread_id=t4.id),
            Dependency(source_thread_id=t3.id, target_thread_id=t4.id),
        ]
    )
    await async_db.commit()

    assert await detect_circular_dependency(999999, t1.id, "thread", async_db) is False


@pytest.mark.asyncio
async def test_update_thread_blocked_status_updates_target(async_db):
    """Single-thread blocked status updater should set denormalized flag."""
    user = User(username="single_update_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    source = Thread(
        title="Source",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    target = Thread(
        title="Target",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([source, target])
    await async_db.flush()

    async_db.add(Dependency(source_thread_id=source.id, target_thread_id=target.id))
    await async_db.commit()

    await update_thread_blocked_status(target.id, user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target)

    assert target.is_blocked is True


@pytest.mark.asyncio
async def test_issue_dependency_blocks_by_next_unread_issue(async_db):
    """Issue dependency should block a thread until prerequisite issue is read."""
    user = User(username="issue_dep_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    source_thread = Thread(
        title="Source",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="not_started",
    )
    target_thread = Thread(
        title="Target",
        format="Comic",
        issues_remaining=2,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="not_started",
    )
    async_db.add_all([source_thread, target_thread])
    await async_db.flush()

    source_issue_1 = Issue(
        thread_id=source_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    source_issue_2 = Issue(
        thread_id=source_thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    target_issue_1 = Issue(
        thread_id=target_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    target_issue_2 = Issue(
        thread_id=target_thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    async_db.add_all([source_issue_1, source_issue_2, target_issue_1, target_issue_2])
    await async_db.flush()

    source_thread.next_unread_issue_id = source_issue_1.id
    target_thread.next_unread_issue_id = target_issue_1.id

    async_db.add(
        Dependency(
            source_issue_id=source_issue_1.id,
            target_issue_id=target_issue_1.id,
        )
    )
    await async_db.commit()

    blocked = await get_blocked_thread_ids(user.id, async_db)
    assert target_thread.id in blocked

    reasons = await get_blocking_explanations(target_thread.id, user.id, async_db)
    assert any("issue #1" in reason.lower() for reason in reasons)

    source_issue_1.status = "read"
    source_issue_1.read_at = datetime.now(UTC)
    await async_db.commit()

    blocked_after = await get_blocked_thread_ids(user.id, async_db)
    assert target_thread.id not in blocked_after


@pytest.mark.asyncio
async def test_dep_on_future_issue_blocks_thread_before_reaching_it(async_db):
    """Dependency on a future issue should block the thread even when next-unread is before it."""
    user = User(username="future_dep_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    source_thread = Thread(
        title="Source",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="not_started",
    )
    target_thread = Thread(
        title="Target",
        format="Comic",
        issues_remaining=2,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="not_started",
    )
    async_db.add_all([source_thread, target_thread])
    await async_db.flush()

    source_issue_1 = Issue(
        thread_id=source_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    source_issue_2 = Issue(
        thread_id=source_thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    target_issue_1 = Issue(
        thread_id=target_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    target_issue_2 = Issue(
        thread_id=target_thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    async_db.add_all([source_issue_1, source_issue_2, target_issue_1, target_issue_2])
    await async_db.flush()

    source_thread.next_unread_issue_id = source_issue_1.id
    target_thread.next_unread_issue_id = target_issue_1.id

    async_db.add(
        Dependency(
            source_issue_id=source_issue_1.id,
            target_issue_id=target_issue_2.id,
        )
    )
    await async_db.commit()

    blocked = await get_blocked_thread_ids(user.id, async_db)
    assert target_thread.id in blocked

    target_issue_1.status = "read"
    target_issue_1.read_at = datetime.now(UTC)
    target_thread.next_unread_issue_id = target_issue_2.id
    await async_db.commit()

    blocked_after = await get_blocked_thread_ids(user.id, async_db)
    assert target_thread.id in blocked_after

    source_issue_1.status = "read"
    source_issue_1.read_at = datetime.now(UTC)
    await async_db.commit()

    blocked_unblocked = await get_blocked_thread_ids(user.id, async_db)
    assert target_thread.id not in blocked_unblocked


@pytest.mark.asyncio
async def test_validate_position_dependency_consistency_warns_on_conflict(async_db):
    """In-thread issue dependencies should warn when they reverse position order."""
    user = User(username="position_validation_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Validation Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="not_started",
    )
    async_db.add(thread)
    await async_db.flush()

    issue_one = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    issue_two = Issue(
        thread_id=thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    async_db.add_all([issue_one, issue_two])
    await async_db.flush()

    async_db.add(
        Dependency(
            source_issue_id=issue_two.id,
            target_issue_id=issue_one.id,
        )
    )
    await async_db.commit()

    warnings = await validate_position_dependency_consistency(thread.id, user.id, async_db)

    assert len(warnings) == 1
    assert 'thread "Validation Thread"' in warnings[0]
    assert "issue #2" in warnings[0]
    assert "issue #1" in warnings[0]
    assert "Position is canonical" in warnings[0]


@pytest.mark.asyncio
async def test_dep_blocks_anticipatorily_before_dep_target(async_db):
    """Dep on issue #3 should block thread when next_unread is issue #1."""
    user = User(username="anticipatory_dep_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    source_thread = Thread(
        title="Source",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=3,
        reading_progress="not_started",
    )
    target_thread = Thread(
        title="Target",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=3,
        reading_progress="not_started",
    )
    async_db.add_all([source_thread, target_thread])
    await async_db.flush()

    source_issue_1 = Issue(
        thread_id=source_thread.id, issue_number="1", position=1, status="unread"
    )
    source_issue_2 = Issue(
        thread_id=source_thread.id, issue_number="2", position=2, status="unread"
    )
    source_issue_3 = Issue(
        thread_id=source_thread.id, issue_number="3", position=3, status="unread"
    )
    target_issue_1 = Issue(
        thread_id=target_thread.id, issue_number="1", position=1, status="unread"
    )
    target_issue_2 = Issue(
        thread_id=target_thread.id, issue_number="2", position=2, status="unread"
    )
    target_issue_3 = Issue(
        thread_id=target_thread.id, issue_number="3", position=3, status="unread"
    )
    async_db.add_all(
        [
            source_issue_1,
            source_issue_2,
            source_issue_3,
            target_issue_1,
            target_issue_2,
            target_issue_3,
        ]
    )
    await async_db.flush()

    source_thread.next_unread_issue_id = source_issue_1.id
    target_thread.next_unread_issue_id = target_issue_1.id

    async_db.add(
        Dependency(
            source_issue_id=source_issue_3.id,
            target_issue_id=target_issue_3.id,
        )
    )
    await async_db.commit()

    blocked = await get_blocked_thread_ids(user.id, async_db)
    assert target_thread.id in blocked

    source_issue_3.status = "read"
    source_issue_3.read_at = datetime.now(UTC)
    await async_db.commit()

    blocked_after = await get_blocked_thread_ids(user.id, async_db)
    assert target_thread.id not in blocked_after


@pytest.mark.asyncio
async def test_dep_does_not_block_when_next_unread_past_dep_target(async_db):
    """Dep on issue #2 should NOT block when next_unread is already issue #3."""
    user = User(username="past_dep_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    source_thread = Thread(
        title="Source",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=3,
        reading_progress="not_started",
    )
    target_thread = Thread(
        title="Target",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=3,
        reading_progress="not_started",
    )
    async_db.add_all([source_thread, target_thread])
    await async_db.flush()

    source_issue_1 = Issue(
        thread_id=source_thread.id, issue_number="1", position=1, status="unread"
    )
    source_issue_2 = Issue(
        thread_id=source_thread.id, issue_number="2", position=2, status="unread"
    )
    target_issue_1 = Issue(thread_id=target_thread.id, issue_number="1", position=1, status="read")
    target_issue_2 = Issue(thread_id=target_thread.id, issue_number="2", position=2, status="read")
    target_issue_3 = Issue(
        thread_id=target_thread.id, issue_number="3", position=3, status="unread"
    )
    async_db.add_all(
        [source_issue_1, source_issue_2, target_issue_1, target_issue_2, target_issue_3]
    )
    await async_db.flush()

    source_thread.next_unread_issue_id = source_issue_1.id
    target_thread.next_unread_issue_id = target_issue_3.id

    async_db.add(
        Dependency(
            source_issue_id=source_issue_1.id,
            target_issue_id=target_issue_2.id,
        )
    )
    await async_db.commit()

    blocked = await get_blocked_thread_ids(user.id, async_db)
    assert target_thread.id not in blocked
