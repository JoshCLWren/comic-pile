"""Tests for move_to_safe_position queue function."""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread
from comic_pile.dependencies import refresh_user_blocked_status
from comic_pile.queue import get_bounded_roll_pool_rows, get_roll_pool, move_to_safe_position


@pytest.mark.asyncio
async def test_move_to_safe_position_no_blocked(
    async_db: AsyncSession, default_user, sample_data
) -> None:
    """With die=d6 and fewer threads than die+1, thread lands at position 4 (back of queue)."""
    thread = sample_data["threads"][0]  # Superman, pos 1
    # Superman is at position 1, die=6 => safe position should be min(7, active_count)
    # Active threads after superman: Batman(2), Flash(4), Aquaman(5) = 4 total
    # So die_size(6) + 1 = 7, but max is 4 => position 4 (back)
    await move_to_safe_position(thread.id, default_user.id, 6, async_db)
    await async_db.refresh(thread)
    # Die size=6, 4 active threads. count blocked in range = 0
    # target = min(6+1+0, 4) = min(7, 4) = 4 (back)
    assert thread.queue_position == 4


@pytest.mark.asyncio
async def test_move_to_safe_position_with_blocked_threads(
    async_db: AsyncSession, default_user, sample_data
) -> None:
    """Blocked threads count as occupied slots in the safe-position calculation."""
    thread = sample_data["threads"][0]  # Superman, pos 1

    # Mark Flash (currently pos 4) as blocked
    flash = sample_data["threads"][3]
    flash.is_blocked = True
    await async_db.flush()

    # Now active threads: Superman(1), Batman(2), Aquaman(3)
    # But Flash(4) is blocked, so there's a blocked thread at seq 4
    # die=6 => die_size(6) + 1 + blocked_in_range(1) = 8, min(8, 3) = 3
    # blocked threads in first (6+0=6) slots: Flash is at seq 4, which is < 6, so yes
    await move_to_safe_position(thread.id, default_user.id, 6, async_db)
    await async_db.refresh(thread)
    assert thread.queue_position == 4  # Went to back (4 is max with 4 active threads)

    # Cleanup
    flash.is_blocked = False
    await async_db.flush()


@pytest.mark.asyncio
async def test_move_to_safe_position_many_threads(
    async_db: AsyncSession, default_user
) -> None:
    """With more than die_size+1 active threads, lands at precise die+1 position."""
    user = default_user
    threads = []
    for i in range(1, 15):
        t = Thread(
            title=f"Thread {i}",
            format="Comic",
            issues_remaining=5,
            queue_position=i,
            status="active",
            user_id=user.id,
        )
        async_db.add(t)
        threads.append(t)
    await async_db.flush()
    for t in threads:
        await async_db.refresh(t)

    target = threads[0]  # pos 1
    await move_to_safe_position(target.id, user.id, 6, async_db)
    await async_db.refresh(target)
    # 14 active threads, die=6, no blocked
    # target = min(6+1+0, 14) = 7
    assert target.queue_position == 7


@pytest.mark.asyncio
async def test_move_to_safe_position_at_back_when_small_pool(
    async_db: AsyncSession, default_user
) -> None:
    """When there are fewer threads than die+1, thread goes to the last position."""
    user = default_user
    threads = []
    for i in range(1, 5):
        t = Thread(
            title=f"Thread {i}",
            format="Comic",
            issues_remaining=5,
            queue_position=i,
            status="active",
            user_id=user.id,
        )
        async_db.add(t)
        threads.append(t)
    await async_db.flush()
    for t in threads:
        await async_db.refresh(t)

    target = threads[0]  # pos 1
    await move_to_safe_position(target.id, user.id, 6, async_db)
    await async_db.refresh(target)
    # 4 active threads, die=6 => target = min(6+1+0, 4) = 4
    assert target.queue_position == 4


@pytest.mark.asyncio
async def test_move_to_safe_position_single_thread_noop(
    async_db: AsyncSession, default_user
) -> None:
    """With only one active thread, moving to safe position is a no-op."""
    user = default_user
    t = Thread(
        title="Lonely Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(t)
    await async_db.flush()
    await async_db.refresh(t)

    await move_to_safe_position(t.id, user.id, 6, async_db)
    await async_db.refresh(t)
    assert t.queue_position == 1


@pytest.mark.asyncio
async def test_move_to_safe_position_blocked_threads_in_range(
    async_db: AsyncSession, default_user
) -> None:
    """Blocked threads within the die range increase the offset."""
    user = default_user
    threads = []
    for i in range(1, 15):
        t = Thread(
            title=f"Thread {i}",
            format="Comic",
            issues_remaining=5,
            queue_position=i,
            is_blocked=(i == 4 or i == 6),
            status="active",
            user_id=user.id,
        )
        async_db.add(t)
        threads.append(t)
    await async_db.flush()
    for t in threads:
        await async_db.refresh(t)

    target = threads[0]  # pos 1
    await move_to_safe_position(target.id, user.id, 6, async_db)
    await async_db.refresh(target)
    # 14 active threads, die=6, blocked at positions 4 and 6
    # Non-blocked before target must be >= 6 (die size).
    # Non-blocked threads (excluding target): pos 2,3,5,7,8,9 → 6th is at pos 9.
    # Target placed at position 9 (right after the 6th non-blocked thread).
    assert target.queue_position == 9


@pytest.mark.asyncio
async def test_move_to_safe_position_many_blocked_before_target_bug_597(
    async_db: AsyncSession, default_user
) -> None:
    """Regression test for issue #597.

    Reproduces the production scenario: many blocked threads are interspersed
    before the target thread. The old formula counted blocked threads in a
    fixed index range and produced a position that still left the target inside
    the roll pool (only 5 non-blocked threads before it with a d6).

    With 25 threads, 10 blocked (positions 3-12), and die=6:
    - Old (broken): the target moved to position 11, with only 5 non-blocked
      threads before it, so it remained selectable.
    - Fixed: the target moves to position 17, after the 6th non-blocked
      thread, guaranteeing it's outside the d6 roll pool.
    """
    user = default_user
    threads = []
    for i in range(1, 26):
        t = Thread(
            title=f"Thread {i}",
            format="Comic",
            issues_remaining=5,
            queue_position=i,
            status="active",
            user_id=user.id,
            is_blocked=(3 <= i <= 12),
        )
        async_db.add(t)
        threads.append(t)
    await async_db.flush()
    for t in threads:
        await async_db.refresh(t)

    # Target is at the front, before the blocked block.
    target = threads[0]  # Thread 1
    await move_to_safe_position(target.id, user.id, 6, async_db)
    await async_db.refresh(target)

    assert target.queue_position == 17

    # Verify the target is NOT in the roll pool (the actual bug symptom).
    pool = await get_roll_pool(user.id, async_db)
    pool_size = min(6, len(pool))
    pool_ids = {t.id for t in pool[:pool_size]}
    assert target.id not in pool_ids, (
        f"Target thread {target.id} is still in the roll pool "
        f"(pool_size={pool_size}) after move_to_safe_position — "
        f"it should be outside the d6 pool!"
    )

    # Also verify by counting non-blocked threads before the target's position.
    result = await async_db.execute(
        select(Thread)
        .where(Thread.user_id == user.id)
        .where(Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    all_active = result.scalars().all()
    target_pos = next(
        t.queue_position for t in all_active if t.id == target.id
    )
    non_blocked_before = sum(
        1
        for t in all_active
        if t.id != target.id
        and not t.is_blocked
        and t.queue_position < target_pos
    )
    assert non_blocked_before >= 6, (
        f"Only {non_blocked_before} non-blocked threads before target at "
        f"position {target_pos} — need >= 6 to be outside d6 pool!"
    )


@pytest.mark.asyncio
async def test_move_to_safe_position_excludes_snoozed_threads_from_roll_pool(
    async_db: AsyncSession, default_user
) -> None:
    """Snoozed threads must not consume slots in the expanded roll pool."""
    user = default_user
    threads = []
    for i in range(1, 15):
        thread = Thread(
            title=f"Snooze Thread {i}",
            format="Comic",
            issues_remaining=5,
            queue_position=i,
            status="active",
            user_id=user.id,
        )
        async_db.add(thread)
        threads.append(thread)
    await async_db.flush()

    target = threads[0]
    snoozed_ids = {threads[1].id, threads[2].id}
    await move_to_safe_position(
        target.id,
        user.id,
        8,
        async_db,
        excluded_thread_ids=snoozed_ids,
    )
    await async_db.refresh(target)

    # The target must follow eight eligible threads. Two snoozed threads occupy
    # raw queue slots, so the target lands at raw position 11, not position 9.
    assert target.queue_position == 11

    result = await async_db.execute(
        select(Thread)
        .where(Thread.user_id == user.id)
        .where(Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    all_active = result.scalars().all()
    eligible_before = sum(
        1
        for thread in all_active
        if thread.id != target.id
        and thread.id not in snoozed_ids
        and thread.queue_position < target.queue_position
    )
    assert eligible_before == 8


@pytest.mark.asyncio
async def test_move_to_safe_position_mixed_issues_dependencies_and_snoozes(
    async_db: AsyncSession, default_user
) -> None:
    """Safe placement must match a mixed issue/dependency/snooze roll pool."""
    user = default_user
    threads = []
    for position in range(1, 26):
        thread = Thread(
            title=f"Mixed pool thread {position}",
            format="Comic",
            issues_remaining=5,
            total_issues=5,
            queue_position=position,
            status="active",
            user_id=user.id,
        )
        async_db.add(thread)
        threads.append(thread)
    await async_db.flush()

    issues = []
    for thread in threads:
        issue = Issue(
            thread_id=thread.id,
            issue_number="1",
            position=1,
            status="unread",
        )
        async_db.add(issue)
        issues.append(issue)
    await async_db.flush()
    for thread, issue in zip(threads, issues, strict=True):
        thread.next_unread_issue_id = issue.id

    # Four issue-level dependencies make queue positions 4-7 unavailable.
    # The source remains unread, so those target threads are genuinely blocked.
    async_db.add_all(
        [
            Dependency(source_issue_id=issues[1].id, target_issue_id=issues[i].id)
            for i in range(3, 7)
        ]
    )
    await async_db.commit()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    target = threads[0]
    snoozed_ids = {threads[7].id, threads[8].id, threads[9].id}
    await move_to_safe_position(
        target.id,
        user.id,
        8,
        async_db,
        excluded_thread_ids=snoozed_ids,
    )
    await async_db.refresh(target)

    # Eligible threads before the target are positions 2-3 and 11-16:
    # two ordinary + six after four blocked and three snoozed = eight.
    assert target.queue_position == 16
    pool = await get_roll_pool(user.id, async_db, list(snoozed_ids))
    assert target.id not in {thread.id for thread in pool[:8]}


@pytest.mark.asyncio
async def test_move_to_safe_position_excludes_skipped_threads_issue_2802(
    async_db: AsyncSession, default_user
) -> None:
    """Regression test for issue #2802: skipped threads must be excluded from safe position calculation.

    This reproduces the bug where a below-threshold rating could immediately return
    the same thread on the next roll when skipped threads shrink the bounded pool.
    """
    user = default_user
    threads = []
    for i in range(1, 12):  # Create 11 threads
        thread = Thread(
            title=f"Thread {i}",
            format="Comic",
            issues_remaining=5,
            queue_position=i,
            status="active",
            user_id=user.id,
        )
        async_db.add(thread)
        threads.append(thread)
    await async_db.flush()

    # Simulate the production scenario:
    # - Thread A (at position 1) will be skipped during a session
    # - Thread B (at position 2) will be rated 3.0, causing d6 -> d8
    # - The safe position calculation must account for thread A being skipped

    thread_a = threads[0]  # Position 1
    thread_b = threads[1]  # Position 2
    skipped_thread_ids = {thread_a.id}

    # First, test that move_to_safe_position correctly excludes skipped threads
    # When thread B is rated on d6, it should move to position 8 (d6 + 1 + 1 skipped)
    await move_to_safe_position(
        thread_b.id,
        user.id,
        6,  # Current die size
        async_db,
        excluded_thread_ids=skipped_thread_ids,
    )
    await async_db.refresh(thread_b)

    # With die=6, 11 total threads, 1 skipped:
    # Target should be at position 8 (6 + 1 + 1 skipped, but max is 11)
    # This ensures thread B is outside the d6 roll pool
    assert thread_b.queue_position == 8, (
        f"Thread B should be at position 8 (die=6 + 1 + 1 skipped), "
        f"but is at position {thread_b.queue_position}"
    )

    # Now verify that thread B is NOT in the bounded roll pool
    # Get the bounded roll pool (simulating what happens during the next roll)
    bounded_rows = await get_bounded_roll_pool_rows(
        user.id,
        async_db,
        6,  # die size = d6
        snoozed_ids=[],  # No snoozed threads
        skipped_ids=skipped_thread_ids,  # Thread A is skipped
    )

    bounded_thread_ids = {row[0].id for row in bounded_rows}
    assert thread_b.id not in bounded_thread_ids, (
        f"Thread B (id={thread_b.id}) should NOT be in the d6 roll pool "
        f"when thread A (id={thread_a.id}) is skipped, but it is present"
    )

    # Now test the expanded die case (d6 -> d8 after rating)
    # Move thread B back to position 2 to simulate the rating scenario
    thread_b.queue_position = 2
    await async_db.flush()

    # Simulate rating thread B 3.0, causing d6 -> d8
    # The safe position calculation should now account for the skipped thread
    await move_to_safe_position(
        thread_b.id,
        user.id,
        8,  # New die size after rating
        async_db,
        excluded_thread_ids=skipped_thread_ids,
    )
    await async_db.refresh(thread_b)

    # With die=8, 11 total threads, 1 skipped:
    # Target should be at position 10 (8 + 1 + 1 skipped, but max is 11)
    # This ensures thread B is outside the d8 roll pool
    assert thread_b.queue_position == 10, (
        f"Thread B should be at position 10 (die=8 + 1 + 1 skipped), "
        f"but is at position {thread_b.queue_position}"
    )

    # Verify thread B is NOT in the expanded d8 roll pool
    bounded_rows_d8 = await get_bounded_roll_pool_rows(
        user.id,
        async_db,
        8,  # die size = d8
        snoozed_ids=[],  # No snoozed threads
        skipped_ids=skipped_thread_ids,  # Thread A is skipped
    )

    bounded_thread_ids_d8 = {row[0].id for row in bounded_rows_d8}
    assert thread_b.id not in bounded_thread_ids_d8, (
        f"Thread B (id={thread_b.id}) should NOT be in the d8 roll pool "
        f"when thread A (id={thread_a.id}) is skipped, but it is present"
    )
