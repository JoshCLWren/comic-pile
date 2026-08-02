"""Queue management functions."""

from collections.abc import Collection
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread

logger = logging.getLogger(__name__)

QueuePositionChanges = dict[int, int]


async def move_to_front(
    thread_id: int, user_id: int, db: AsyncSession, commit: bool = True
) -> QueuePositionChanges:
    """Move thread to front of queue and return changed prior positions.

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        db: Async database session.
        commit: Whether to commit inside this helper.

    Returns:
        Mapping of changed thread IDs to their previous queue positions.
    """
    result = await db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    )
    target_thread = result.scalar_one_or_none()
    if not target_thread:
        return {}

    original_position = target_thread.queue_position
    if original_position == 1:
        return {}

    affected_result = await db.execute(
        select(Thread.id, Thread.queue_position)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .where(Thread.queue_position < original_position)
    )
    changes = {row.id: row.queue_position for row in affected_result.all()}
    changes[target_thread.id] = original_position

    await db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .where(Thread.queue_position < original_position)
        .values(queue_position=Thread.queue_position + 1)
    )
    target_thread.queue_position = 1
    if commit:
        await db.commit()
    return changes


async def move_to_back(
    thread_id: int,
    user_id: int,
    db: AsyncSession,
    commit: bool = True,
) -> QueuePositionChanges:
    """Move thread to the back and return changed prior positions.

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        db: Async database session.
        commit: Whether to commit inside this helper.

    Returns:
        Mapping of changed thread IDs to their previous queue positions.
    """
    result = await db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    )
    target_thread = result.scalar_one_or_none()
    if not target_thread:
        return {}

    original_position = target_thread.queue_position

    result = await db.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position.desc())
        .limit(1)
    )
    max_active_position = result.scalar()
    if max_active_position is None:
        return {}

    destination_position = max(original_position, max_active_position)
    affected_result = await db.execute(
        select(Thread.id, Thread.queue_position)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position > original_position)
    )
    changes = {row.id: row.queue_position for row in affected_result.all()}

    if original_position == destination_position and not changes:
        return {}

    changes[target_thread.id] = original_position
    await db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position > original_position)
        .values(queue_position=Thread.queue_position - 1)
    )
    target_thread.queue_position = destination_position
    if commit:
        await db.commit()
    return changes


async def move_to_position(
    thread_id: int,
    user_id: int,
    new_position: int,
    db: AsyncSession,
    do_commit: bool = True,
) -> QueuePositionChanges:
    """Move thread to a specific sequential position.

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        new_position: Target sequential position (1-indexed).
        db: Async database session.
        do_commit: Whether to commit inside this helper.

    Returns:
        Mapping of changed thread IDs to their previous queue positions.
    """
    logger.info(
        "move_to_position ENTRY: thread_id=%s, user_id=%s, new_position=%s",
        thread_id,
        user_id,
        new_position,
    )

    result = await db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    )
    target_thread = result.scalar_one_or_none()
    if not target_thread:
        logger.error("Thread %s not found for user %s", thread_id, user_id)
        return {}

    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position)
    )
    all_threads = list(result.scalars().all())
    original_positions = {thread.id: thread.queue_position for thread in all_threads}

    thread_count = len(all_threads)
    current_sequential_pos = next(
        (i + 1 for i, thread in enumerate(all_threads) if thread.id == thread_id), 0
    )
    if current_sequential_pos == 0:
        logger.error("Target thread %s not found in active queue", thread_id)
        return {}

    if new_position < 1:
        raise ValueError(f"Position must be at least 1, got {new_position}")
    if new_position > thread_count:
        raise ValueError(
            f"Position {new_position} is out of range. Maximum position is {thread_count}."
        )

    for index, thread in enumerate(all_threads, start=1):
        thread.queue_position = index

    if current_sequential_pos < new_position:
        for index, thread in enumerate(all_threads, start=1):
            if thread.id != thread_id and current_sequential_pos < index <= new_position:
                thread.queue_position -= 1
        target_thread.queue_position = new_position
    elif current_sequential_pos > new_position:
        for index, thread in enumerate(all_threads, start=1):
            if thread.id != thread_id and new_position <= index < current_sequential_pos:
                thread.queue_position += 1
        target_thread.queue_position = new_position

    changes = {
        thread.id: original_positions[thread.id]
        for thread in all_threads
        if thread.queue_position != original_positions[thread.id]
    }
    if do_commit:
        await db.commit()
    return changes


async def move_to_safe_position(
    thread_id: int,
    user_id: int,
    die_size: int,
    db: AsyncSession,
    excluded_thread_ids: Collection[int] | None = None,
) -> QueuePositionChanges:
    """Move a thread just beyond the current rollable die range.

    Args:
        thread_id: Thread to reposition.
        user_id: Thread owner.
        die_size: Current die size from the dice ladder.
        db: Async database session (caller handles commit/rollback).
        excluded_thread_ids: Thread IDs excluded from the current roll pool.

    Returns:
        Mapping of changed thread IDs to their previous queue positions.
    """
    excluded_ids = set(excluded_thread_ids or ())

    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position)
    )
    all_active = list(result.scalars().all())
    rollable = [t for t in all_active if not t.is_blocked and t.id not in excluded_ids]

    target_rollable_index = next(
        (i for i, thread in enumerate(rollable) if thread.id == thread_id), -1
    )
    if target_rollable_index == -1 or len(rollable) <= 1:
        return {}
    if target_rollable_index >= die_size:
        return {}

    non_blocked_seen = 0
    target_seq = len(all_active)
    for index, thread in enumerate(all_active):
        if thread.id == thread_id:
            continue
        if not thread.is_blocked and thread.id not in excluded_ids:
            non_blocked_seen += 1
        if non_blocked_seen >= die_size:
            target_seq = index + 1
            break

    target_seq = min(target_seq, len(all_active))
    target_current_seq = next(
        (i + 1 for i, thread in enumerate(all_active) if thread.id == thread_id), 0
    )
    if target_current_seq == target_seq:
        return {}

    original_positions = {thread.id: thread.queue_position for thread in all_active}
    for index, thread in enumerate(all_active, start=1):
        thread.queue_position = index

    if target_current_seq < target_seq:
        for index, thread in enumerate(all_active, start=1):
            if thread.id != thread_id and target_current_seq < index <= target_seq:
                thread.queue_position -= 1
    else:
        for index, thread in enumerate(all_active, start=1):
            if thread.id != thread_id and target_seq <= index < target_current_seq:
                thread.queue_position += 1

    target_thread = next(thread for thread in all_active if thread.id == thread_id)
    target_thread.queue_position = target_seq
    return {
        thread.id: original_positions[thread.id]
        for thread in all_active
        if thread.queue_position != original_positions[thread.id]
    }


async def shuffle_queue(user_id: int, db: AsyncSession) -> int:
    """Randomize the order of active queue threads for a user.

    Args:
        user_id: The user whose active queue should be shuffled.
        db: The async database session.

    Returns:
        Number of active threads that were shuffled.
    """
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position, Thread.id)
    )
    threads = list(result.scalars().all())

    if len(threads) < 2:
        return len(threads)

    random.shuffle(threads)
    for position, thread in enumerate(threads, start=1):
        thread.queue_position = position

    await db.commit()
    return len(threads)


async def get_roll_pool(
    user_id: int,
    db: AsyncSession,
    snoozed_ids: list[int] | None = None,
    collection_id: int | None = None,
) -> list[Thread]:
    """Get all active threads ordered by position.

    Args:
        user_id: The user ID to filter threads by.
        db: The database session.
        snoozed_ids: Optional list of thread IDs to exclude from the pool.
        collection_id: Optional collection ID to filter threads by.

    Returns:
        List of active threads ordered by queue position.
    """
    query = (
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
    )

    if snoozed_ids:
        query = query.where(Thread.id.not_in(snoozed_ids))

    if collection_id is not None:
        query = query.where(Thread.collection_id == collection_id)

    query = query.where(Thread.is_blocked.is_(False))
    query = query.order_by(Thread.queue_position)

    result = await db.execute(query)
    threads = result.scalars().all()
    return list(threads)


async def get_stale_threads(user_id: int, db: AsyncSession, days: int = 7) -> list[Thread]:
    """Get threads not read in specified days."""
    cutoff_date = datetime.now(UTC) - timedelta(days=days)

    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(False))
        .where((Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None)))
        .order_by(Thread.last_activity_at.asc().nullsfirst())
    )
    threads = result.scalars().all()
    return list(threads)
