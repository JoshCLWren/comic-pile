"""Queue management functions."""

from collections.abc import Collection, Sequence
from datetime import UTC, datetime, timedelta
import logging
import random
from typing import Any, NamedTuple
from sqlalchemy import and_, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.models import Issue, Thread
from app.repositories.reading_eligibility_queries import (
    blocked_predicate,
    candidate_predicate,
    frontier_expression,
)
from app.services.queue_pagination import build_sort_order
from app.services.reading_eligibility_service import get_execution_eligibility

logger = logging.getLogger(__name__)

ADVISORY_LOCK_NAMESPACE = 699001
QueuePositionChanges = dict[int, int]


class ActiveQueueThread(NamedTuple):
    """The active-queue columns `move_to_safe_position` actually needs.

    Safe-position placement reads only identity, ordering, and blocked state for
    every active thread. Selecting the full ``Thread`` entity instead made
    SQLAlchemy build one ORM instance per active thread on every rate call that
    lands in the safe-position branch, so the projection is pinned here to the
    three columns the placement algorithm consumes.
    """

    id: int
    queue_position: int
    is_blocked: bool


async def acquire_queue_lock(user_id: int, db: AsyncSession) -> None:
    """Acquire the transaction-scoped advisory lock that serializes a queue.

    Every writer that reads and rewrites a reader's queue positions must hold
    this lock for the rest of its transaction, so a concurrent move or shuffle
    can neither interleave with it nor be undone by it.

    Autoflush is suppressed while acquiring the lock: a caller may already
    have pending row changes, and flushing them first would take row locks
    before this lock and invert the global lock order against a concurrent
    shuffler (deadlock). The pending changes still flush at the next query,
    which now runs after the lock is held.

    Args:
        user_id: Thread owner whose queue is being modified.
        db: Async database session.
    """
    with db.no_autoflush:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:ns, :uid)"),
            {"ns": ADVISORY_LOCK_NAMESPACE, "uid": user_id},
        )


def _sync_cached_queue_positions(db: AsyncSession, positions: dict[int, int]) -> None:
    """Synchronize cached Thread objects without per-object SELECTs."""
    if not positions:
        return

    for obj in list(db.identity_map.values()):
        if isinstance(obj, Thread) and obj.id in positions:
            set_committed_value(obj, "queue_position", positions[obj.id])


def _split_position_rows(rows: Sequence[Any]) -> tuple[dict[int, int], QueuePositionChanges]:
    """Split queue UPDATE rows into new positions and changed old positions."""
    positions: dict[int, int] = {}
    changes: QueuePositionChanges = {}
    for row in rows:
        positions[row.id] = row.queue_position
        if row.queue_position != row.old_position:
            changes[row.id] = row.old_position
    return positions, changes


_MOVE_POSITION_SQL = text("""
    WITH ranked AS (
        SELECT
            id,
            queue_position AS old_position,
            row_number() OVER (ORDER BY queue_position, id) AS seq
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
    END,
    queue_position_is_manual = (
        t.queue_position_is_manual OR (t.id = :tid AND CAST(:manual AS BOOLEAN))
    )
    FROM ranked, target
    WHERE t.id = ranked.id
    RETURNING t.id, t.queue_position, ranked.old_position
""")

_MOVE_TO_BACK_SQL = text("""
    WITH ranked AS (
        SELECT
            id,
            queue_position AS old_position,
            row_number() OVER (ORDER BY queue_position, id) AS seq
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
    END,
    queue_position_is_manual = (
        t.queue_position_is_manual OR (t.id = :tid AND CAST(:manual AS BOOLEAN))
    )
    FROM ranked, target, bounds
    WHERE t.id = ranked.id
    RETURNING t.id, t.queue_position, ranked.old_position
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
    SET queue_position = shuffled.new_position,
        queue_position_is_manual = FALSE
    FROM shuffled
    WHERE t.id = shuffled.thread_id
      AND t.user_id = :uid
      AND t.status = 'active'
      AND t.queue_position >= 1
    RETURNING t.id, t.queue_position
""")


async def move_to_front(
    thread_id: int,
    user_id: int,
    db: AsyncSession,
    commit: bool = True,
    manual: bool = False,
) -> QueuePositionChanges:
    """Move an active thread to the normalized queue front.

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        db: Async database session.
        commit: Whether to commit inside this helper.
        manual: Whether the reader explicitly chose this placement. Explicit
            placements are remembered so a later automatic rating demotion does
            not discard them (#3638).

    Returns:
        Mapping of changed thread IDs to their previous positions.
    """
    return await move_to_position(
        thread_id, user_id, 1, db, do_commit=commit, manual=manual
    )


async def move_to_back(
    thread_id: int,
    user_id: int,
    db: AsyncSession,
    commit: bool = True,
    manual: bool = False,
) -> QueuePositionChanges:
    """Move a thread behind the active queue and return its delta.

    The target is included even when it has just been marked completed.

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        db: Async database session.
        commit: Whether to commit inside this helper.
        manual: Whether the reader explicitly chose this placement. Explicit
            placements are remembered so a later automatic rating demotion does
            not discard them (#3638).

    Returns:
        Mapping of changed thread IDs to their previous positions.
    """
    await acquire_queue_lock(user_id, db)

    result = await db.execute(
        _MOVE_TO_BACK_SQL,
        {"uid": user_id, "tid": thread_id, "manual": manual},
    )
    positions, changes = _split_position_rows(result.fetchall())
    _sync_cached_queue_positions(db, positions)

    if commit:
        await db.commit()
    return changes


async def active_display_rows(
    user_id: int,
    db: AsyncSession,
) -> list[tuple[int, int, bool]]:
    """Return ``(id, queue_position, blocked)`` in the reader-visible order.

    The Queue lists readable rows ahead of blocked rows and numbers them in that
    order, so this sequence is the ordinal space every Queue surface displays.
    Reposition requests arrive in this space; ``move_to_position`` translates
    them back into raw ranks before writing.

    Args:
        user_id: Thread owner whose active queue is read.
        db: Async database session.

    Returns:
        One tuple per active queued thread, in displayed order.
    """
    eligibility = await get_execution_eligibility(db, user_id)
    blocked = blocked_predicate(eligibility)
    result = await db.execute(
        select(Thread.id, Thread.queue_position, blocked)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(*build_sort_order("position", eligibility))
    )
    return [(int(row[0]), int(row[1]), bool(row[2])) for row in result.all()]


async def move_to_position(
    thread_id: int,
    user_id: int,
    new_position: int,
    db: AsyncSession,
    do_commit: bool = True,
    manual: bool = False,
) -> QueuePositionChanges:
    """Move an active thread to a normalized sequential position.

    ``new_position`` is the reader-visible Queue ordinal that the Queue rows,
    the Reposition dialog, and ``ThreadResponse.queue_position`` all display.
    The Queue orders readable rows ahead of blocked rows, so a blocked thread
    keeps its raw ``queue_position`` while displaying after every readable
    series. The requested ordinal is translated into the matching raw rank
    before the set-based move; otherwise an entered position persisted two
    ranks early whenever blocked rows held lower raw positions (#4181).

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        new_position: Target sequential position (1-indexed).
        db: Async database session.
        do_commit: Whether to commit inside this helper.
        manual: Whether the reader explicitly chose this placement. Explicit
            placements are remembered so a later automatic rating demotion does
            not discard them (#3638).

    Returns:
        Mapping of changed thread IDs to their previous positions.
    """
    logger.debug(
        "move_to_position ENTRY: thread_id=%d, user_id=%d, new_position=%d",
        thread_id,
        user_id,
        new_position,
    )

    await acquire_queue_lock(user_id, db)

    row_result = await db.execute(
        select(Thread.id, Thread.queue_position, Thread.status)
        .where(Thread.id == thread_id)
        .where(Thread.user_id == user_id)
    )
    row = row_result.one_or_none()

    if not row:
        logger.error("Thread %d not found for user %d", thread_id, user_id)
        if do_commit:
            await db.commit()
        return {}

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
        return {}

    display_rows = await active_display_rows(user_id, db)
    active_total = len(display_rows)
    current_ordinal = next(
        (index for index, active_row in enumerate(display_rows, start=1) if active_row[0] == thread_id),
        0,
    )
    if current_ordinal == 0:
        logger.error("Target thread %d not found in active threads list", thread_id)
        if do_commit:
            await db.commit()
        return {}

    if new_position < 1:
        raise ValueError(f"Position must be at least 1, got {new_position}")
    if new_position > active_total:
        raise ValueError(
            f"Position {new_position} is out of range. Maximum position is {active_total}."
        )

    # A blocked row always displays after every readable row, so it can only
    # reach ordinals inside its own group. Clamp a request that crosses groups
    # to the nearest reachable ordinal instead of persisting an unreachable
    # rank that the row badges can never show.
    first_blocked = next(
        (index for index, active_row in enumerate(display_rows) if active_row[2]),
        active_total,
    )
    target_is_blocked = display_rows[current_ordinal - 1][2]
    group_start = first_blocked + 1 if target_is_blocked else 1
    group_end = active_total if target_is_blocked else first_blocked
    target_ordinal = min(max(new_position, group_start), group_end)

    logger.debug(
        "Moving thread %d from ordinal %d to ordinal %d (raw position %d)",
        thread_id,
        current_ordinal,
        target_ordinal,
        queue_position,
    )

    if target_ordinal == current_ordinal:
        if manual:
            await db.execute(
                update(Thread)
                .where(Thread.id == thread_id)
                .where(Thread.user_id == user_id)
                .values(queue_position_is_manual=True)
            )
        if do_commit:
            await db.commit()
        return {}

    # `_MOVE_POSITION_SQL` rewrites every active row to its raw rank and places
    # the target at `new_pos`, so the ordinal has to be expressed as the raw
    # rank of the row that currently holds it.
    anchor_id, anchor_position, _ = display_rows[target_ordinal - 1]
    raw_target = 1 + sum(
        1
        for active_row in display_rows
        if (active_row[1], active_row[0]) < (anchor_position, anchor_id)
    )

    return await _move_to_raw_rank(
        thread_id, user_id, raw_target, db, do_commit=do_commit, manual=manual
    )


async def _move_to_raw_rank(
    thread_id: int,
    user_id: int,
    raw_rank: int,
    db: AsyncSession,
    do_commit: bool = False,
    manual: bool = False,
) -> QueuePositionChanges:
    """Place an active thread at a stored queue rank, shifting rows between.

    ``raw_rank`` is a dense stored ``queue_position`` rank, the same space
    ``_MOVE_POSITION_SQL`` orders rows in and the same order the roll pool is
    drawn from. So it is the write surface for callers that compute their
    target from stored ranks — rating-time placement via
    ``move_to_safe_position`` — rather than the reader-visible ordinal space
    ``move_to_position`` translates from (#4181).

    Args:
        thread_id: Thread to move.
        user_id: Thread owner.
        raw_rank: Target dense stored rank (1-indexed by ``queue_position, id``).
        db: Async database session.
        do_commit: Whether to commit inside this helper.
        manual: Whether the reader explicitly chose this placement. Explicit
            placements are remembered so a later automatic rating demotion does
            not discard them (#3638).

    Returns:
        Mapping of changed thread IDs to their previous positions.

    Raises:
        ValueError: When ``raw_rank`` is outside the active queue ranks.
    """
    count_result = await db.execute(
        select(func.count())
        .select_from(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
    )
    active_total = int(count_result.scalar_one())
    if raw_rank < 1:
        raise ValueError(f"Position must be at least 1, got {raw_rank}")
    if raw_rank > active_total:
        raise ValueError(
            f"Position {raw_rank} is out of range. Maximum position is {active_total}."
        )

    move_result = await db.execute(
        _MOVE_POSITION_SQL,
        {
            "uid": user_id,
            "tid": thread_id,
            "new_pos": raw_rank,
            "manual": manual,
        },
    )
    positions, changes = _split_position_rows(move_result.fetchall())
    _sync_cached_queue_positions(db, positions)

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Final queue state after operation:")
        final_result = await db.execute(
            select(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.status == "active")
            .where(Thread.queue_position >= 1)
            .order_by(Thread.queue_position, Thread.id)
        )
        final_queue = final_result.scalars().all()

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
        "move_to_position SUCCESS: thread %d moved to stored rank %d",
        thread_id,
        raw_rank,
    )
    return changes


async def move_to_safe_position(
    thread_id: int,
    user_id: int,
    die_size: int,
    db: AsyncSession,
    excluded_thread_ids: Collection[int] | None = None,
) -> QueuePositionChanges:
    """Move a thread just beyond the current die range.

    Only threads that the next roll could actually select are counted, so
    ``excluded_thread_ids`` must be the same complete exclusion set the roll
    path uses (issue #3696). Callers that pass only part of it place the thread
    too early and let the next roll repeat the just-rated series.

    Constrained behavior, stated explicitly so callers do not promise an
    immediate non-repeat that cannot be delivered:

    - The thread is counted by rank among non-blocked, non-excluded threads,
      and is placed immediately after the ``die_size``-th such thread.
    - When fewer than ``die_size`` eligible threads remain, the target is placed
      after every eligible thread instead, which is the end of the queue's
      eligible region. An immediate non-repeat is not guaranteed in that case
      because the bounded pool covers the whole eligible set.
    - When the thread is already ranked at or beyond ``die_size``, or is the only
      eligible thread, the position is left unchanged.
    - Placement is written in the stored rank space via ``_move_to_raw_rank``,
      the same space the roll pool itself is drawn from. It must not route
      through the reader-visible ordinal translation in ``move_to_position``:
      the Queue re-numbers readable rows ahead of blocked ones, so a stored
      rank handed in as an ordinal would push a rated series past extra
      readable series (#4181).

    Args:
        thread_id: Thread to reposition.
        user_id: Thread owner.
        die_size: Current die size from the dice ladder.
        db: Async database session.
        excluded_thread_ids: Thread IDs excluded from the roll pool.

    Returns:
        Mapping of changed thread IDs to their previous positions.
    """
    await acquire_queue_lock(user_id, db)

    eligibility = await get_execution_eligibility(db, user_id)
    excluded_ids = set(excluded_thread_ids or ())
    result = await db.execute(
        select(Thread.id, Thread.queue_position, Thread.is_blocked)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position, Thread.id)
    )
    all_active = [ActiveQueueThread(*row) for row in result.all()]
    available = (
        set(eligibility.candidate_ids())
        if eligibility is not None
        else {t.id for t in all_active if not t.is_blocked}
    )
    rollable = [t for t in all_active if t.id in available and t.id not in excluded_ids]

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
        if thread.id in available and thread.id not in excluded_ids:
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

    # The target sequence is a stored rank. Keep it out of ``move_to_position``:
    # that helper now treats its argument as the displayed Queue ordinal, so a
    # raw rank passed there lands too far down whenever blocked rows occupy
    # lower stored positions (#4181).
    return await _move_to_raw_rank(
        thread_id,
        user_id,
        target_seq,
        db,
        do_commit=False,
        manual=False,
    )


async def shuffle_queue(user_id: int, db: AsyncSession) -> int:
    """Randomize active queue positions in one array-backed update.

    Args:
        user_id: The user whose active queue should be shuffled.
        db: The async database session.

    Returns:
        Number of active threads that were shuffled.
    """
    await acquire_queue_lock(user_id, db)

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
) -> list[Thread]:
    """Get all active threads ordered by position.

    Args:
        user_id: The user ID to filter threads by.
        db: The database session.
        snoozed_ids: Optional list of thread IDs to exclude from the pool.

    Returns:
        List of active threads ordered by queue position.
    """
    eligibility = await get_execution_eligibility(db, user_id)
    query = (
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
    )

    if snoozed_ids:
        query = query.where(Thread.id.not_in(snoozed_ids))

    query = query.where(candidate_predicate(eligibility))
    query = query.order_by(Thread.queue_position)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_roll_pool_rows(
    user_id: int,
    db: AsyncSession,
    snoozed_ids: list[int] | None = None,
    skipped_ids: list[int] | None = None,
) -> list[tuple[Thread, int, str | None]]:
    """Get the active roll pool enriched with issue-tracking read state.

    Each row carries the Thread, the number of unread issues, and the
    next-unread-issue number. Folding the unread count and issue metadata into
    the pool query removes per-thread round trips from the roll selection path.

    The returned list is in queue-position order with blocked and snoozed
    threads excluded, but is **not** bounded to any die size.  Callers that
    need a bounded candidate set should use :func:`get_bounded_roll_pool_rows`
    so that contextual weighting logic cannot draw from outside the die pool.

    Args:
        user_id: The user ID to filter threads by.
        db: The database session.
        snoozed_ids: Optional list of thread IDs to exclude from the pool.
        skipped_ids: Optional list of thread IDs to exclude from the pool (skipped during current session).

    Returns:
        List of ``(Thread, unread_count, next_issue_number)`` tuples ordered by
        queue position.
    """
    # Index justification: unread_counts uses Issue.status + Issue.thread_id,
    # covered by existing index `ix_issue_thread_is_read` (`thread_id`, `status`).
    eligibility = await get_execution_eligibility(db, user_id)
    if eligibility is not None:
        # Option E has already evaluated every unread count and frontier.
        # Joining Issue and aggregating every unread Issue across all readers
        # would re-run work whose SQL results are discarded by this branch.
        query = (
            select(Thread)
            .where(
                Thread.user_id == user_id,
                Thread.status == "active",
                Thread.queue_position >= 1,
                candidate_predicate(eligibility),
            )
            .order_by(Thread.queue_position)
        )
        if snoozed_ids:
            query = query.where(Thread.id.not_in(snoozed_ids))
        if skipped_ids:
            query = query.where(Thread.id.not_in(skipped_ids))
        threads = (await db.scalars(query)).all()
        return [
            (
                thread,
                eligibility.unread_counts.get(thread.id, 0),
                (
                    eligibility.issue_numbers.get(next_id)
                    if (next_id := eligibility.threads[thread.id].next_issue_id) is not None
                    else None
                ),
            )
            for thread in threads
        ]

    # Legacy mode continues to use persisted frontier and SQL unread counts.
    frontier = frontier_expression(eligibility)
    unread_counts = (
        select(Issue.thread_id.label("thread_id"), func.count(Issue.id).label("unread_count"))
        .where(Issue.status == "unread")
        .group_by(Issue.thread_id)
        .subquery()
    )
    query = (
        select(
            Thread,
            func.coalesce(unread_counts.c.unread_count, 0).label("unread_count"),
            Issue.issue_number.label("next_issue_number"),
        )
        .outerjoin(unread_counts, unread_counts.c.thread_id == Thread.id)
        .outerjoin(
            Issue,
            and_(Issue.id == frontier, Issue.status == "unread"),
        )
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .where(candidate_predicate(eligibility))
        .order_by(Thread.queue_position)
    )

    if snoozed_ids:
        query = query.where(Thread.id.not_in(snoozed_ids))

    if skipped_ids:
        query = query.where(Thread.id.not_in(skipped_ids))

    result = await db.execute(query)
    return [
        (
            row[0],
            eligibility.unread_counts.get(row[0].id, 0) if eligibility is not None else row[1],
            (
                eligibility.issue_numbers.get(nid)
                if (nid := eligibility.threads[row[0].id].next_issue_id) is not None
                else None
            )
            if eligibility is not None
            else row[2],
        )
        for row in result
    ]


async def get_bounded_roll_pool_rows(
    user_id: int,
    db: AsyncSession,
    current_die: int,
    snoozed_ids: list[int] | None = None,
    skipped_ids: list[int] | None = None,
) -> list[tuple[Thread, int, str | None]]:
    """Return the bounded roll-candidate pool for weighted chooser integration.

    Applies the die-size boundary on top of :func:`get_roll_pool_rows` so that
    contextual weighting logic cannot draw candidates from outside the active
    die pool.  The pool remains uniform within these boundaries in this phase;
    weighting factors are layered on later without changing the boundary.

    Args:
        user_id: The user ID to filter threads by.
        db: The database session.
        current_die: The current die size from the dice ladder; caps pool size.
        snoozed_ids: Optional list of thread IDs to exclude from the pool.
        skipped_ids: Optional list of thread IDs to exclude from the pool (skipped during current session).

    Returns:
        List of ``(Thread, unread_count, next_issue_number)`` tuples, in
        queue-position order, truncated to ``current_die`` entries.
    """
    rows = await get_roll_pool_rows(user_id, db, snoozed_ids, skipped_ids)
    return rows[:current_die]


async def get_stale_threads(
    user_id: int,
    db: AsyncSession,
    days: int = 7,
    snoozed_ids: list[int] | None = None,
) -> list[Thread]:
    """Get threads not read in the specified number of days.

    Args:
        user_id: Owner of the threads.
        db: Async database session.
        days: Number of days after which a thread is considered stale.
        snoozed_ids: Thread IDs currently snoozed in the session; these are
            excluded from the stale result.

    Returns:
        Active, unblocked threads whose last activity predates the cutoff,
        ordered oldest activity first (nulls first).
    """
    eligibility = await get_execution_eligibility(db, user_id)
    cutoff_date = datetime.now(UTC) - timedelta(days=days)

    query = (
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(candidate_predicate(eligibility))
        .where((Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None)))
        .order_by(Thread.last_activity_at.asc().nullsfirst())
    )
    if snoozed_ids:
        query = query.where(Thread.id.not_in(snoozed_ids))

    result = await db.execute(query)
    return list(result.scalars().all())
