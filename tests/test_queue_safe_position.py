"""Tests for move_to_safe_position queue function."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread
from comic_pile.queue import move_to_safe_position


@pytest.mark.asyncio
async def test_move_to_safe_position_no_blocked(
    async_db: AsyncSession, default_user, sample_data
) -> None:
    """With die=d6 and no blocked threads, thread lands at position 7."""
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
    # 14 active threads, die=6
    # blocked threads in first (6+0=6) positions: seq 4 and seq 6 are blocked = 2
    # target = min(6+1+2, 14) = min(9, 14) = 9
    assert target.queue_position == 9
