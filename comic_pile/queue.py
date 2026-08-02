"""Queue management functions."""

from collections.abc import Collection
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

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


def _sync_cached_queue_positions(db: AsyncSession, positions: dict[int, int]) -> None:
    """Synchronize cached Thread objects without issuing per-object SELECTs."""
    if not positions:
        return

    for obj in list(db.identity_map.values()):
        if isinstance(obj, Thread) and obj.id in positions:
            set_committed_value(obj, "queue_position", positions[obj.id])


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
        WHEN target.seq < :new_pos THEN
            CASE WHEN ranked.seq > target.seq AND ranked.seq <= :new_pos
                 THEN ranked.seq - 1 ELSE ranked.seq END
        ELSE
            CASE WHEN ranked.seq >= :new_pos AND ranked.seq < target.seq
                 THEN ranked.seq + 1 ELSE ranked.seq END
    END
    FROM ranked, target
    WHERE t.id = ranked.id
    RETURNING t.id, t.queue_position
""")

_MOVE_TO_BACK_SQL = text("""
    WITH ranked AS (
        SELECT id, row_number() OVER (ORDER BY queue_position, id) AS seq
        FROM threads
        WHERE user_id = :uid
          AND queue_position >= 1
          AND (status = 'active' OR id = :tid)
    ),
    target AS (
        SELECT seq FROM ranked WHERE id = :tid
    ),
    bounds AS (
        SELECT count(*) AS total FROM ranked
    )
    UPDATE threads AS t
    SET queue_position = CASE
        WHEN t.id = :tid THEN bounds.total
        WHEN ranked.seq > target.seq THEN ranked.seq - 1
        ELSE ranked.seq
    END
    FROM ranked, target, bounds
    WHERE t.id = ranked.id
    RETURNING t.id, t.queue_position
""")

_SHUFFLE_SQL = text("""
    WITH shuffled AS (
        SELECT thread_id, new_position
        FROM unnest(
            CAST(:thread_ids AS INTEGER[]),
            CAST(:positions AS INTEGER[])
        ) AS shuffled(thread_id, new_position)
    )
    UPDATE threads AS t
    SET queue_position = shuffled.new_position
    FROM shuffled
    WHERE t.id = shuffled.thread_id
      AND t.user_id = :uid
      AND t.status = 'active'
      AND t.queue_position >= 1
    RETURNING t.id, t.queue_position
""")


async def move_to_front(
    thread_id: int, user_id: int, db: AsyncSession, commit: bool = True
) -> None:
    """Move an active thread to the normalized front of its queue.

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        db: Async database session.
        commit: Whether to commit inside this helper.
    """
    await move_to_position(thread_id, user_id, 1, db, do_commit=commit)


async def move_to_back(thread_id: int, user_id: int, db: AsyncSession, commit: bool = True) -> None:
    """Move a thread behind the active queue while normalizing active positions.

    The target is included even when it has just been marked completed, which
    preserves the rating flow's behavior of compacting the remaining active
    queue and placing the completed thread immediately after it.

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        db: Async database session.
        commit: Whether to commit inside this helper.
    """
    await _acquire_queue_lock(user_id, db)

    result = await db.execute(
        _MOVE_TO_BACK_SQL,
        {"uid": user_id, "tid": thread_id},
    )
    positions = {row.id: row.queue_position for row in result.fetchall()}
    _sync_cached_queue_positions(db, positions)

    if commit:
        await db.commit()


async def move_to_position(
    thread_id: int,
    user_id: int,
    new_position: int,
    db: AsyncSession,
    do_commit: bool = True,
) -> None:
    """Move an active thread to a normalized sequential position.

    Uses a single CASE-based UPDATE driven by a window-function ranking.
    Gap and duplicate normalization happens in the same statement as the move,
    and returned positions synchronize cached ORM objects without N additional
    database round trips.

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        new_position: Target sequential position (1-indexed).
        db: Async database session.
        do_commit: Whether to commit inside this helper.
    """
    logger.debug(
        "move_to_position ENTRY: thread_id=%d, user_id=%d, new_position=%d",
        thread_id,
        user_id,
        new_position,
    )

    await _acquire_queue_lock(user_id, db)

    result = await db.execute(
        select(Thread.id, Thread.queue_position, Thread.status)
        .where(Thread.id == thread_id)
        .where(Thread.user_id == user_id)
    )
    row = result.one_or_none()

    if not row:
        logger.error("Thread %d not found for user %d", thread_id, user_id)
        if do_commit:
            await db.commit()
        return

    thread_id_val, queue_position, status = row
    logger.debug(
        "Thread found: id=%d, user_id=%d, current_position=%d, status='%s'",
        thread_id_val,
        user_id,
        queue_position,
        status,
    )

    if status != "active" or queue_position < 1:
        logger.error("Target thread %d not found in active threads list", thread_id)
        if do_commit:
            await db.commit()
        return

    result = await db.execute(
        text(
            """
            SELECT
                count(*)::integer AS total,
                count(*) FILTER (
                    WHERE queue_position < :queue_position
                       OR (queue_position = :queue_position AND id <= :tid)
                )::integer AS seq
            FROM threads
            WHERE user_id = :uid
              AND status = 'active'
              AND queue_position >= 1
            """
        ),
        {
            "uid": user_id,
            "tid": thread_id,
            "queue_position": queue_position,
        },
    )
    thread_count, old_seq = result.one()
    logger.debug("Active thread count: %d", thread_count)

    if new_position < 1:
        raise ValueError(f"Position must be at least 1, got {new_position}")

    if new_position > thread_count:
        raise ValueError(
            f"Position {new_position} is out of range. Maximum position is {thread_count}."
        )

    logger.debug(
        "Moving thread %d from sequential position %d to %d",
        thread_id,
        old_seq,
        new_position,
    )

    result = await db.execute(
        _MOVE_POSITION_SQL,
        {"uid": user_id, "tid": thread_id, "new_pos": new_position},
    )
    positions = {row.id: row.queue_position for row in result.fetchall()}
    _sync_cached_queue_positions(db, positions)

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Final queue state after operation:")
        result = await db.execute(
            select(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.status == "active")
            .where(Thread.queue_position >= 1)
            .order_by(Thread.queue_position, Thread.id)
        )
        final_queue = result.scalars().all()

        for thread in final_queue:
            logger.debug(
                "  Position %d: Thread %d ('%s...')",
                thread.queue_position,
                thread.id,
                thread.title[:50],
            )

    if do_commit:
        await db.commit()

    logger.debug(
        "move_to_position SUCCESS: thread %d moved to position %d",
        thread_id,
        new_position,
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
    position must be computed by counting non-blocked threads, not raw queue
    positions. The queue lock covers both this calculation and the subsequent
    move so a concurrent reorder cannot invalidate the target rank.

    Args:
        thread_id: Thread to reposition.
        user_id: Thread owner.
        die_size: Current die size from the dice ladder.
        db: Async database session (caller handles commit/rollback).
        excluded_thread_ids: Thread IDs excluded from the current roll pool,
            such as threads snoozed in the active session.
    """
    await _acquire_queue_lock(user_id, db)

    excluded_ids = set(excluded_thread_ids or ())

    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position, Thread.id)
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
    """Randomize active queue positions for a user in one array-backed update.

    Args:
        user_id: The user whose active queue should be shuffled.
        db: The async database session.

    Returns:
        Number of active threads that were shuffled.
    """
    await _acquire_queue_lock(user_id, db)

    result = await db.execute(
        select(Thread.id)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position, Thread.id)
    )
    active_ids = [row[0] for row in result.fetchall()]

    if len(active_ids) < 2:
        await db.commit()
        return len(active_ids)

    shuffled_ids = list(active_ids)
    random.shuffle(shuffled_ids)

    result = await db.execute(
        _SHUFFLE_SQL,
        {
            "uid": user_id,
            "thread_ids": shuffled_ids,
            "positions": list(range(1, len(shuffled_ids) + 1)),
        },
    )
    positions = {row.id: row.queue_position for row in result.fetchall()}
    _sync_cached_queue_positions(db, positions)

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
