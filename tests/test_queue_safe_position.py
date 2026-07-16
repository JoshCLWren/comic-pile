"""Tests for move_to_safe_position queue function."""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread
from comic_pile.queue import get_roll_pool, move_to_safe_position


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
