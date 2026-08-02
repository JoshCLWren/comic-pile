"""Queue management functions."""

from collections.abc import Collection
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select as sa_select

from app.models import Thread

logger = logging.getLogger(__name__)

ADVISORY_LOCK_NAMESPACE = 699001


async def _acquire_queue_lock(user_id: int, db: AsyncSession) -> None:
    """Acquire a transaction-scoped advisory lock keyed on user_id.

    The lock uses the two-integer form of pg_advisory_xact_lock so it is
    re-entrant within the same transaction and releases automatically on
    commit or rollback.

    Args:
        user_id: Thread owner whose queue is being modified.
        db: Async database session.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :uid)"),
        {"ns": ADVISORY_LOCK_NAMESPACE, "uid": user_id},
    )


async def _refresh_queue_positions(db: AsyncSession, user_id: int) -> None:
    """Refresh ``queue_position`` on every cached Thread for *user_id*.

    Core-level UPDATE statements bypass the ORM unit-of-work, so cached
    ORM objects remain stale after a queue modification.  Refreshing only
    the position column brings them in sync with the database.
    """
    for obj in list(db.identity_map.values()):
        if isinstance(obj, Thread) and obj.user_id == user_id:
            await db.refresh(obj, attribute_names=["queue_position"])


_MOVE_POSITION_SQL = text("""
    WITH ranked AS (
        SELECT id, row_number() OVER (ORDER BY queue_position, id) AS seq
        FROM threads
        WHERE user_id = :uid AND status = 'active' AND queue_position >= 1
    ),
    target AS (
        SELECT seq FROM ranked WHERE id = :tid
    )
    UPDATE threads AS t
    SET queue_position = CASE
        WHEN t.id = :tid THEN :new_pos
        WHEN (SELECT seq FROM target) < :new_pos THEN
            CASE WHEN ranked.seq > (SELECT seq FROM target) AND ranked.seq <= :new_pos
                 THEN ranked.seq - 1 ELSE ranked.seq END
        ELSE
            CASE WHEN ranked.seq >= :new_pos AND ranked.seq < (SELECT seq FROM target)
                 THEN ranked.seq + 1 ELSE ranked.seq END
    END
    FROM ranked
    WHERE t.id = ranked.id
""")


async def move_to_front(
    thread_id: int, user_id: int, db: AsyncSession, commit: bool = True
) -> None:
    """Move thread to front of queue.

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        db: Async database session.
        commit: Whether to commit inside this helper.
    """
    await _acquire_queue_lock(user_id, db)

    result = await db.execute(
        sa_select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    )
    target_thread = result.scalar_one_or_none()
    if not target_thread:
        return

    original_position = target_thread.queue_position
    if original_position == 1:
        return

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


async def move_to_back(thread_id: int, user_id: int, db: AsyncSession, commit: bool = True) -> None:
    """Move thread to back of queue.

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        db: Async database session.
        commit: Whether to commit inside this helper.
    """
    await _acquire_queue_lock(user_id, db)

    result = await db.execute(
        sa_select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    )
    target_thread = result.scalar_one_or_none()
    if not target_thread:
        return

    original_position = target_thread.queue_position

    result = await db.execute(
        sa_select(Thread.queue_position)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position.desc())
        .limit(1)
    )
    max_position = result.scalar()

    if max_position is None:
        return

    if original_position == max_position:
        return

    await db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position > original_position)
        .values(queue_position=Thread.queue_position - 1)
    )
    target_thread.queue_position = max_position
    if commit:
        await db.commit()


async def move_to_position(
    thread_id: int, user_id: int, new_position: int, db: AsyncSession,
    do_commit: bool = True,
) -> None:
    """Move thread to specific position.

    Uses a single CASE-based UPDATE driven by a single linear scan of
    active thread IDs — eliminating the previous O(n²) nested list scans
    and the unconditional post-move full queue reload.  Gap / duplicate
    positions are normalised to sequential 1..N in the same statement.

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        new_position: Target sequential position (1-indexed).
        db: Async database session.
        do_commit: Whether to commit inside this helper.
    """
    logger.info(
        "move_to_position ENTRY: thread_id=%d, user_id=%d, new_position=%d",
        thread_id,
        user_id,
        new_position,
    )

    await _acquire_queue_lock(user_id, db)

    logger.debug("Retrieving thread %d for user %d", thread_id, user_id)
    result = await db.execute(
        sa_select(Thread.id, Thread.queue_position, Thread.title, Thread.status)
        .where(Thread.id == thread_id)
        .where(Thread.user_id == user_id)
    )
    row = result.one_or_none()

    if not row:
        logger.error("Thread %d not found for user %d", thread_id, user_id)
        return

    thread_id_val, queue_position, title, status = row

    logger.info(
        "Thread found: id=%d, title='%s', "
        "user_id=%d, current_position=%d, "
        "status='%s'",
        thread_id_val,
        title,
        user_id,
        queue_position,
        status,
    )

    old_position = queue_position
    logger.info("Current thread position: %d", old_position)

    result = await db.execute(
        sa_select(Thread.id)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position, Thread.id)
    )
    active_ids = [row[0] for row in result.fetchall()]

    thread_count = len(active_ids)
    logger.info("Active thread count: %d", thread_count)

    old_seq = next(
        (i + 1 for i, tid in enumerate(active_ids) if tid == thread_id), 0
    )

    if old_seq == 0:
        logger.error("Target thread %d not found in active threads list", thread_id)
        return

    if new_position < 1:
        raise ValueError(f"Position must be at least 1, got {new_position}")

    if new_position > thread_count:
        raise ValueError(
            f"Position {new_position} is out of range. Maximum position is {thread_count}."
        )

    logger.info("Final target position: %d (original: %d)", new_position, old_position)

    if old_seq == new_position:
        logger.info(
            "Thread %d already at sequential position %d, no movement needed",
            thread_id,
            new_position,
        )
        return

    await db.execute(
        _MOVE_POSITION_SQL,
        {"uid": user_id, "tid": thread_id, "new_pos": new_position},
    )

    await _refresh_queue_positions(db, user_id)

    logger.debug("Committing database transaction")
    if do_commit:
        await db.commit()

    logger.info("move_to_position SUCCESS: thread %d moved to position %d", thread_id, new_position)

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Final queue state after operation:")
        result = await db.execute(
            sa_select(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.queue_position >= 1)
            .order_by(Thread.queue_position)
        )
        final_queue = result.scalars().all()

        for thread in final_queue:
            logger.debug(
                "  Position %d: Thread %d ('%s...')",
                thread.queue_position,
                thread.id,
                thread.title[:50],
            )


async def move_to_safe_position(
    thread_id: int,
    user_id: int,
    die_size: int,
    db: AsyncSession,
    excluded_thread_ids: Collection[int] | None = None,
) -> None:
    """Move thread to a position just beyond the current die range.

    Instead of sending a low-rated thread to the very back (which can bury it
    for months), place it just past the die-size threshold in the **rollable**
    pool (non-blocked active threads), so it won't reappear in the next roll
    pool while keeping it realistically reachable.

    The roll pool (``get_roll_pool``) excludes blocked threads, so the target
    position must be computed by counting non-blocked threads — not raw queue
    positions.  This fixes a bug (#597) where blocked threads inflated the
    ``queue_position`` values but were excluded from the roll pool, causing
    the rated thread to remain selectable.

    Example (die=d6, no blocked threads):
        Position 1-6: rollable pool
        Rated thread -> position 7

    Example (die=d6, 10 blocked threads interspersed in positions 3-12):
        Rollable pool: positions 1, 2, 13, 14, ... (blocked skipped)
        Rated thread -> placed after the 6th non-blocked thread

    Args:
        thread_id: Thread to reposition.
        user_id: Thread owner.
        die_size: Current die size from the dice ladder.
        db: Async database session (caller handles commit/rollback).
        excluded_thread_ids: Thread IDs excluded from the current roll pool,
            such as threads snoozed in the active session.
    """
    excluded_ids = set(excluded_thread_ids or ())

    result = await db.execute(
        sa_select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position)
    )
    all_active = list(result.scalars().all())

    rollable = [t for t in all_active if not t.is_blocked and t.id not in excluded_ids]

    target_rollable_index = next(
        (i for i, t in enumerate(rollable) if t.id == thread_id), -1
    )
    if target_rollable_index == -1:
        return

    if len(rollable) <= 1:
        return

    if target_rollable_index >= die_size:
        return

    non_blocked_seen = 0
    target_seq = len(all_active)
    for i, t in enumerate(all_active):
        if t.id == thread_id:
            continue
        if not t.is_blocked and t.id not in excluded_ids:
            non_blocked_seen += 1
        if non_blocked_seen >= die_size:
            target_seq = i + 1
            break

    target_seq = min(target_seq, len(all_active))

    target_current_seq = next(
        (i + 1 for i, t in enumerate(all_active) if t.id == thread_id), 0
    )
    if target_current_seq == target_seq:
        return

    await move_to_position(thread_id, user_id, target_seq, db, do_commit=False)


async def shuffle_queue(user_id: int, db: AsyncSession) -> int:
    """Randomize the order of active queue threads for a user.

    Uses a single CASE-based UPDATE to assign new positions in bulk,
    eliminating the previous row-by-row ORM mutations and reducing
    the operation to a single SQL statement.

    Args:
        user_id: The user whose active queue should be shuffled.
        db: The async database session.

    Returns:
        Number of active threads that were shuffled.
    """
    await _acquire_queue_lock(user_id, db)

    result = await db.execute(
        sa_select(Thread.id)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position, Thread.id)
    )
    active_ids = [row[0] for row in result.fetchall()]

    if len(active_ids) < 2:
        return len(active_ids)

    shuffled_ids = list(active_ids)
    random.shuffle(shuffled_ids)

    case_expr = case(
        *[(Thread.id == tid, pos) for pos, tid in enumerate(shuffled_ids, start=1)],
        else_=Thread.queue_position,
    )
    await db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .values(queue_position=case_expr)
    )

    await _refresh_queue_positions(db, user_id)

    await db.commit()
    return len(active_ids)


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
        sa_select(Thread)
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
        sa_select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(False))
        .where((Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None)))
        .order_by(Thread.last_activity_at.asc().nullsfirst())
    )
    threads = result.scalars().all()

    return list(threads)
