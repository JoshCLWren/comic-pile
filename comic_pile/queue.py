"""Queue management functions."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Thread

logger = logging.getLogger(__name__)


def move_to_front(thread_id: int, user_id: int, db: Session) -> None:
    """Move thread to front of queue."""
    target_thread = db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    ).scalar_one_or_none()
    if not target_thread:
        return

    original_position = target_thread.queue_position
    if original_position == 1:
        return

    db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .where(Thread.queue_position < original_position)
        .values(queue_position=Thread.queue_position + 1)
    )
    target_thread.queue_position = 1
    db.commit()


def move_to_back(thread_id: int, user_id: int, db: Session) -> None:
    """Move thread to back of queue."""
    target_thread = db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    ).scalar_one_or_none()
    if not target_thread:
        return

    original_position = target_thread.queue_position

    max_position = db.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position.desc())
        .limit(1)
    ).scalar()

    if max_position is None:
        return

    if original_position == max_position:
        return

    db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position > original_position)
        .values(queue_position=Thread.queue_position - 1)
    )
    target_thread.queue_position = max_position
    db.commit()


def move_to_position(thread_id: int, user_id: int, new_position: int, db: Session) -> None:
    """Move thread to specific position."""
    logger.info(
        f"move_to_position ENTRY: thread_id={thread_id}, user_id={user_id}, new_position={new_position}"
    )

    logger.debug(f"Retrieving thread {thread_id} for user {user_id}")
    target_thread = db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    ).scalar_one_or_none()

    if not target_thread:
        logger.error(f"Thread {thread_id} not found for user {user_id}")
        return

    logger.info(
        f"Thread found: id={target_thread.id}, title='{target_thread.title}', "
        f"user_id={target_thread.user_id}, current_position={target_thread.queue_position}, "
        f"status='{target_thread.status}'"
    )

    old_position = target_thread.queue_position
    logger.info(f"Current thread position: {old_position}")

    if new_position < 1:
        logger.warning(f"new_position {new_position} < 1, setting to 1")
        new_position = 1

    # Get all active threads sorted by current position
    all_threads = (
        db.execute(
            select(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.status == "active")
            .where(Thread.queue_position >= 1)
            .order_by(Thread.queue_position)
        )
        .scalars()
        .all()
    )

    thread_count = len(all_threads)
    logger.info(f"Active thread count: {thread_count}")

    if new_position > thread_count:
        logger.warning(
            f"new_position {new_position} > thread_count {thread_count}, capping to thread_count"
        )
        new_position = thread_count

    logger.info(f"Final target position: {new_position} (original: {old_position})")

    # Find the current sequential position of our target thread
    current_sequential_pos = next(
        (i + 1 for i, thread in enumerate(all_threads) if thread.id == thread_id), 0
    )

    if current_sequential_pos == 0:
        logger.error(f"Target thread {thread_id} not found in active threads list")
        return

    if current_sequential_pos == new_position:
        logger.info(
            f"Thread {thread_id} already at sequential position {new_position}, no movement needed"
        )
        return

    # Normalize all positions to be sequential first
    for i, thread in enumerate(all_threads):
        normalized_position = i + 1
        if thread.queue_position != normalized_position:
            thread.queue_position = normalized_position

    logger.info("Normalized all thread positions to sequential values")

    # Now apply the move using the normalized positions
    if current_sequential_pos < new_position:
        logger.info(
            f"Moving thread BACKWARD: sequential {current_sequential_pos} -> {new_position}"
        )

        # Shift threads at current position + 1 to new_position back by 1
        for thread in all_threads:
            if thread.id != thread_id:
                current_thread_seq_pos = next(
                    (i + 1 for i, t in enumerate(all_threads) if t.id == thread.id), 0
                )
                if current_sequential_pos < current_thread_seq_pos <= new_position:
                    thread.queue_position -= 1

        target_thread.queue_position = new_position
        logger.info(f"Set target thread {thread_id} position to {new_position}")

    else:  # current_sequential_pos > new_position
        logger.info(f"Moving thread FORWARD: sequential {current_sequential_pos} -> {new_position}")

        # Shift threads at new_position to current_position - 1 forward by 1
        for thread in all_threads:
            if thread.id != thread_id:
                current_thread_seq_pos = next(
                    (i + 1 for i, t in enumerate(all_threads) if t.id == thread.id), 0
                )
                if new_position <= current_thread_seq_pos < current_sequential_pos:
                    thread.queue_position += 1

        target_thread.queue_position = new_position
        logger.info(f"Set target thread {thread_id} position to {new_position}")

    logger.debug("Committing database transaction")
    db.commit()

    logger.info(f"move_to_position SUCCESS: thread {thread_id} moved to position {new_position}")

    # Show final queue state for debugging
    logger.debug("Final queue state after operation:")
    final_queue = (
        db.execute(
            select(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.queue_position >= 1)
            .order_by(Thread.queue_position)
        )
        .scalars()
        .all()
    )

    for thread in final_queue:
        logger.debug(
            f"  Position {thread.queue_position}: Thread {thread.id} ('{thread.title[:50]}...')"
        )


def get_roll_pool(user_id: int, db: Session) -> list[Thread]:
    """Get all active threads ordered by position."""
    threads = (
        db.execute(
            select(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.status == "active")
            .where(Thread.queue_position >= 1)
            .order_by(Thread.queue_position)
        )
        .scalars()
        .all()
    )

    return list(threads)


def get_stale_threads(user_id: int, db: Session, days: int = 7) -> list[Thread]:
    """Get threads not read in specified days."""
    cutoff_date = datetime.now(UTC) - timedelta(days=days)

    threads = (
        db.execute(
            select(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.status == "active")
            .where((Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None)))
            .order_by(Thread.last_activity_at.asc().nullsfirst())
        )
        .scalars()
        .all()
    )

    return list(threads)
