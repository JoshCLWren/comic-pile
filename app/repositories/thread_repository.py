"""Thread query construction and persistence.

All SQLAlchemy access for the ``Thread`` model family lives here. Functions
return ORM models or plain values; callers (services) own transactions.
"""

from datetime import datetime
from typing import NotRequired, TypedDict

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.sql.selectable import ScalarSelect
from sqlalchemy.orm import aliased

from app.services.reading_eligibility_service import ReadingEligibilitySnapshot
from app.repositories.reading_eligibility_queries import candidate_predicate

from app.models import Issue, Thread
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.thread import EXCLUDED_STATUS
from app.services.queue_pagination import (
    QueueCursor,
    QueueSort,
    build_cursor_filter,
    build_sort_order,
)


async def get_thread(db: AsyncSession, thread_id: int) -> Thread | None:
    """Return a thread by primary key without ownership filtering.

    Args:
        db: Database session.
        thread_id: Primary key of the thread.

    Returns:
        The thread, or None when it does not exist.
    """
    return await db.get(Thread, thread_id)


async def lock_thread(db: AsyncSession, thread_id: int) -> Thread | None:
    """Lock one thread row for a reviewed repair or other writer.

    Args:
        db: Database session.
        thread_id: Primary key of the thread.

    Returns:
        The locked thread, or None when it does not exist.
    """
    result = await db.execute(select(Thread).where(Thread.id == thread_id).with_for_update())
    return result.scalar_one_or_none()


async def find_owned(
    db: AsyncSession, user_id: int, thread_id: int, *, for_update: bool = False
) -> Thread | None:
    """Find a thread by ID scoped to its owner.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.
        for_update: Lock the row for update when True.

    Returns:
        The owned thread, or None when absent or foreign.
    """
    query = select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def threads_by_ids(db: AsyncSession, thread_ids: set[int]) -> dict[int, Thread]:
    """Load threads by primary key into a mapping.

    Args:
        db: Database session.
        thread_ids: Primary keys to load; an empty set returns an empty mapping.

    Returns:
        Mapping of thread ID to thread for every existing ID.
    """
    if not thread_ids:
        return {}
    result = await db.execute(select(Thread).where(Thread.id.in_(thread_ids)))
    return {thread.id: thread for thread in result.scalars().all()}


async def threads_for_user(db: AsyncSession, user_id: int) -> list[Thread]:
    """Load every thread owned by a user.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        All threads belonging to the user.
    """
    result = await db.execute(select(Thread).where(Thread.user_id == user_id))
    return list(result.scalars().all())


async def max_queue_position(db: AsyncSession, user_id: int) -> int:
    """Return the highest position in a user's active queue (0 if empty)."""
    result = await db.execute(
        select(func.max(Thread.queue_position))
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
    )
    return int(result.scalar_one() or 0)


async def acquire_queue_lock(db: AsyncSession, user_id: int) -> None:
    """Take the per-reader queue lock before this transaction writes any row.

    Queue writers that may later renumber must take this lock before they
    dirty or flush thread rows. Every move and shuffle takes the same
    transaction-scoped advisory lock first and row locks second, so acquiring
    it first here keeps one global lock order and prevents a deadlock with a
    concurrent shuffle.

    Autoflush is suppressed by the queue helper so this call itself cannot
    flush pending row changes first. Re-acquiring the lock later in the same
    transaction is a no-op.

    Args:
        db: Database session.
        user_id: Owner of the queue being modified.
    """
    from comic_pile.queue import acquire_queue_lock as _acquire_queue_lock

    await _acquire_queue_lock(user_id, db)


async def renormalize_queue_positions(db: AsyncSession, user_id: int) -> None:
    """Rewrite active queue positions as a dense 1..N sequence.

    Takes the transaction-scoped per-reader queue lock that every move and
    shuffle also takes, before reading positions. Without it, a concurrent
    reorder could commit between this read and flush, and the rewrite would
    then put the old order back and undo that reorder.

    The lock is taken with autoflush suppressed so it is acquired before this
    transaction writes any row. Every queue writer then takes the lock first
    and row locks second, which is the ordering that cannot deadlock against a
    concurrent move or shuffle.

    Args:
        db: Database session.
        user_id: Owner of the queue being renumbered.
    """
    await acquire_queue_lock(db, user_id)
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position, Thread.id)
    )
    threads = result.scalars().all()
    for index, thread in enumerate(threads, start=1):
        thread.queue_position = index
    await db.flush()


async def find_recent_duplicate(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    format_value: str,
    issues_remaining: int,
    since: datetime,
) -> Thread | None:
    """Find the most recent thread matching a create-submission fingerprint.

    Backs the create endpoint's idempotency window for #3466: a double-clicked
    "Create Series" submits the same payload twice, and the second submit must
    merge into the thread created by the first instead of inserting a duplicate.

    Args:
        db: Database session.
        user_id: Owner of the candidate thread.
        title: Series title, compared case-insensitively.
        format_value: Normalized format value to match exactly.
        issues_remaining: Remaining issue count to match exactly.
        since: Only threads created at or after this instant are considered.

    Returns:
        The most recently created matching thread, or None when no duplicate
        exists inside the window.
    """
    stmt = (
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(func.lower(Thread.title) == title.lower())
        .where(Thread.format == format_value)
        .where(Thread.issues_remaining == issues_remaining)
        .where(Thread.created_at >= since)
        .order_by(Thread.created_at.desc(), Thread.id.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def fetch_stale_threads(
    db: AsyncSession,
    user_id: int,
    cutoff_date: datetime,
    snoozed_ids: list[int] | None = None,
    page_size: int | None = None,
    eligibility: ReadingEligibilitySnapshot | None = None,
) -> list[Thread]:
    """Fetch active, unblocked threads whose last activity predates a cutoff.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        cutoff_date: Threads last read before this instant are stale.
        snoozed_ids: Thread IDs currently snoozed in the session; these are
            excluded from the stale result.
        page_size: Optional maximum number of results to return.

        eligibility: Shared live result, or None for legacy execution.

    Returns:
        Stale threads ordered oldest activity first (nulls first), capped to
        ``page_size`` when provided.
    """
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
    if page_size is not None:
        query = query.limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_active_threads(db: AsyncSession, user_id: int) -> int:
    """Count a user's active queue threads (authoritative total).

    The membership predicate matches the active-queue contract used by
    repositioning and shuffle exactly (``status == "active"`` and
    ``queue_position >= 1``), so the total is independent of the loaded page,
    search filter, and sort order (see issue #2568).

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        Number of active queue threads owned by the user.
    """
    result = await db.execute(
        select(func.count())
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
    )
    return int(result.scalar_one())


def _queue_series_documents() -> ScalarSelect[object]:
    """Project confirmed series documents in the existing page read.

    Documents follow the canonical confirmed-identity order used elsewhere:
    highest mapping confidence first, then stable identity id. The Queue service
    interprets only the first document so one row never mixes metadata from two
    series identities.
    """
    return (
        select(
            func.json_agg(
                aggregate_order_by(
                    ExternalIdentity.metadata_json,
                    ThreadExternalSeriesMapping.confidence.desc().nullslast(),
                    ExternalIdentity.id,
                )
            )
        )
        .select_from(ThreadExternalSeriesMapping)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
        )
        .where(ThreadExternalSeriesMapping.thread_id == Thread.id)
        .where(ThreadExternalSeriesMapping.status == "confirmed")
        .correlate(Thread)
        .scalar_subquery()
    )


def _series_documents(raw: object) -> list[dict[str, object]]:
    """Normalize the JSON aggregate without hydrating ORM identities."""
    if not isinstance(raw, list):
        return []
    return [
        {str(key): value for key, value in item.items()} for item in raw if isinstance(item, dict)
    ]


async def fetch_queue_page(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None,
    sort: QueueSort,
    cursor: QueueCursor | None,
    limit: int,
    series_metadata_map: dict[int, list[dict[str, object]]] | None = None,
    eligibility: ReadingEligibilitySnapshot | None = None,
    position_map: dict[int, int] | None = None,
) -> list[Thread]:
    """Fetch one deterministic page of a user's ACTIVE threads for the queue list.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        search: Normalized case-insensitive title substring, or None.
        sort: Validated sort order key with deterministic tie-breakers.
        cursor: Decoded continuation cursor, or None for the first page.
        limit: Maximum number of threads to return.
        series_metadata_map: Optional output map of confirmed series documents.

        eligibility: Shared live result, or None for legacy execution.

        position_map: Optional output map populated with whole-Queue display ranks.

    Returns:
        Active threads in canonical page order, at most ``limit`` rows.
    """
    ranks = (
        select(
            Thread.id.label("thread_id"),
            func.row_number()
            .over(order_by=build_sort_order("position", eligibility))
            .label("position"),
        )
        .where(Thread.user_id == user_id, Thread.status == "active")
        .subquery()
    )
    query = (
        select(Thread, func.coalesce(ranks.c.position, 0), _queue_series_documents()).outerjoin(
            ranks, ranks.c.thread_id == Thread.id
        )
    ).where(
        Thread.user_id == user_id,
        Thread.status == "active",
    )

    if search:
        query = query.where(Thread.title.ilike(f"%{search}%"))

    # Apply deterministic sort order with tie-breakers
    for col in build_sort_order(sort, eligibility):
        query = query.order_by(col)

    # Apply opaque cursor-based pagination
    if cursor is not None:
        query = query.where(build_cursor_filter(cursor, eligibility))

    query = query.limit(limit)
    result = await db.execute(query)
    rows = result.all()
    if position_map is not None:
        position_map.update({thread.id: position for thread, position, _metadata in rows})
    if series_metadata_map is not None:
        series_metadata_map.update(
            {thread.id: _series_documents(metadata) for thread, _position, metadata in rows}
        )
    return [thread for thread, _position, _metadata in rows]


async def fetch_completed_page(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None,
    sort: QueueSort,
    cursor: QueueCursor | None,
    limit: int,
    series_metadata_map: dict[int, list[dict[str, object]]] | None = None,
) -> list[Thread]:
    """Fetch one deterministic page of a user's COMPLETED threads for the finished series.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        search: Normalized case-insensitive title substring, or None.
        sort: Validated sort order key with deterministic tie-breakers.
        cursor: Decoded continuation cursor, or None for the first page.
        limit: Maximum number of threads to return.
        series_metadata_map: Optional output map of confirmed series documents.

    Returns:
        Completed threads in canonical page order, at most ``limit`` rows.

    Note:
        Callers normalize ``position`` to ``created`` before calling (completed
        threads hold no live queue positions). The shared
        :func:`build_sort_order` helper keeps the ORDER BY columns and the
        keyset cursor filter on the same contract for every sort.
    """
    query = select(Thread, _queue_series_documents()).where(
        Thread.user_id == user_id, Thread.status == "completed"
    )

    if search:
        query = query.where(Thread.title.ilike(f"%{search}%"))

    # Apply deterministic sort order with tie-breakers (shared with the
    # active-queue path so ordering and cursor filters cannot diverge).
    for col in build_sort_order(sort):
        query = query.order_by(col)

    # Apply opaque cursor-based pagination
    if cursor is not None:
        query = query.where(build_cursor_filter(cursor))

    query = query.limit(limit)
    result = await db.execute(query)
    rows = result.all()
    if series_metadata_map is not None:
        series_metadata_map.update(
            {thread.id: _series_documents(metadata) for thread, metadata in rows}
        )
    return [thread for thread, _metadata in rows]


async def fetch_excluded_page(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None,
    sort: QueueSort,
    cursor: QueueCursor | None,
    limit: int,
    series_metadata_map: dict[int, list[dict[str, object]]] | None = None,
) -> list[Thread]:
    """Fetch one deterministic page of a user's EXCLUDED threads.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        search: Normalized case-insensitive title substring, or None.
        sort: Validated sort order key with deterministic tie-breakers.
        cursor: Decoded continuation cursor, or None for the first page.
        limit: Maximum number of threads to return.
        series_metadata_map: Optional output map of confirmed series documents.

    Returns:
        Excluded threads in canonical page order, at most ``limit`` rows.
    """
    query = select(Thread, _queue_series_documents()).where(
        Thread.user_id == user_id,
        Thread.status == EXCLUDED_STATUS,
    )

    if search:
        query = query.where(Thread.title.ilike(f"%{search}%"))

    for col in build_sort_order(sort):
        query = query.order_by(col)

    if cursor is not None:
        query = query.where(build_cursor_filter(cursor))

    query = query.limit(limit)
    result = await db.execute(query)
    rows = result.all()
    if series_metadata_map is not None:
        series_metadata_map.update(
            {thread.id: _series_documents(metadata) for thread, metadata in rows}
        )
    return [thread for thread, _metadata in rows]


async def fetch_excluded_thread_ids(db: AsyncSession, user_id: int) -> list[int]:
    """Fetch the IDs of every thread this reader excluded from the queue.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        Ascending thread IDs whose durable queue exclusion is still in effect.
    """
    result = await db.execute(
        select(Thread.id).where(
            Thread.user_id == user_id,
            Thread.status == EXCLUDED_STATUS,
        )
    )
    return sorted(result.scalars().all())


async def fetch_completed_threads(db: AsyncSession, user_id: int) -> list[Thread]:
    """Fetch a user's completed threads, newest created first.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        Completed threads ordered by creation date descending.
    """
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "completed")
        .order_by(Thread.created_at.desc())
    )
    return list(result.scalars().all())


async def fetch_active_threads(db: AsyncSession, user_id: int) -> list[Thread]:
    """Fetch a user's active threads in queue order.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        Active threads ordered by queue position.
    """
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    return list(result.scalars().all())


async def insert_thread(db: AsyncSession, thread: Thread) -> None:
    """Persist a newly constructed thread.

    Args:
        db: Database session.
        thread: Thread instance to add to the session.
    """
    db.add(thread)


async def shift_active_queue_positions(db: AsyncSession, user_id: int) -> None:
    """Move every active thread of a user back by one queue position.

    Args:
        db: Database session.
        user_id: Owner of the threads.
    """
    await db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .values(queue_position=Thread.queue_position + 1)
    )


async def delete_thread(db: AsyncSession, thread: Thread) -> None:
    """Delete a thread row via the session.

    Args:
        db: Database session.
        thread: Thread instance to delete.
    """
    await db.delete(thread)


async def delete_threads_by_ids(db: AsyncSession, thread_ids: set[int], user_id: int) -> None:
    """Delete threads by ID, scoped to their owner.

    Args:
        db: Database session.
        thread_ids: Primary keys to delete.
        user_id: Owner that must own every deleted thread.
    """
    await db.execute(
        delete(Thread).where(Thread.id.in_(thread_ids)).where(Thread.user_id == user_id)
    )


async def fetch_repair_candidate_ids(
    db: AsyncSession,
    *,
    user_id: int | None = None,
) -> tuple[list[int], list[int]]:
    """Return candidate thread IDs and affected owner IDs for state repair.

    Args:
        db: Async database session.
        user_id: When set, scope candidates to one user.

    Returns:
        Tuple of (candidate thread IDs ordered by ID, sorted owner IDs).
    """
    candidate_selects = [
        select(Thread.id, Thread.user_id).where(
            Thread.status == "completed",
            Thread.total_issues.is_not(None),
        ),
        select(Thread.id, Thread.user_id).where(
            Thread.status == "active",
            Thread.issues_remaining <= 0,
        ),
    ]
    if user_id is not None:
        candidate_selects = [stmt.where(Thread.user_id == user_id) for stmt in candidate_selects]

    candidate_ids: list[int] = []
    owner_ids: set[int] = set()
    for statement in candidate_selects:
        result = await db.execute(statement.order_by(Thread.id))
        for thread_id, owner_id in result.all():
            candidate_ids.append(thread_id)
            owner_ids.add(owner_id)

    return candidate_ids, sorted(owner_ids)


async def fetch_locked_repair_candidates(
    db: AsyncSession,
    thread_ids: list[int],
) -> list[Thread]:
    """Load and lock candidate threads for repair by ID.

    Args:
        db: Async database session.
        thread_ids: Candidate thread IDs to load and lock.

    Returns:
        Candidate threads locked for update, ordered by ID.
    """
    if not thread_ids:
        return []

    result = await db.execute(
        select(Thread).where(Thread.id.in_(thread_ids)).order_by(Thread.id).with_for_update()
    )
    return list(result.scalars().all())


async def fetch_locked_repair_candidates_rechecked(
    db: AsyncSession,
    *,
    user_id: int | None = None,
) -> list[Thread]:
    """Fetch repair candidates after rechecking conditions under locks.

    Locks affected owners' queue locks, then selects and revalidates candidates
    to avoid overwriting concurrent edits.
    """
    candidate_ids, owner_ids = await fetch_repair_candidate_ids(db, user_id=user_id)
    for owner_id in owner_ids:
        await acquire_queue_lock(db, owner_id)
    if not candidate_ids:
        return []

    # Recheck conditions after acquiring locks to avoid overwriting concurrent edits
    result = await db.execute(
        select(Thread)
        .where(Thread.id.in_(candidate_ids))
        .where(
            or_(
                and_(Thread.status == "completed", Thread.total_issues.is_not(None)),
                and_(Thread.status == "active", Thread.issues_remaining <= 0),
            )
        )
        .order_by(Thread.id)
        .with_for_update()
    )
    return list(result.scalars().all())


async def fetch_threads_for_natural_order_scan(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    thread_id: int | None = None,
    limit: int | None = None,
) -> list[Thread]:
    """Return issue-tracking threads that own at least one issue row.

    The reviewed natural-order repair preflight uses this scan. It does not
    infer dependencies or change read state.

    Args:
        db: Database session.
        user_id: Optional owner filter for a bounded, per-user pass.
        thread_id: Optional single-thread filter.
        limit: Optional maximum number of threads to return.

    Returns:
        Matching threads ordered by ID.
    """
    query = (
        select(Thread)
        .where(Thread.total_issues.is_not(None))
        .where(Thread.id.in_(select(Issue.thread_id).distinct()))
        .order_by(Thread.id)
    )
    if user_id is not None:
        query = query.where(Thread.user_id == user_id)
    if thread_id is not None:
        query = query.where(Thread.id == thread_id)
    if limit is not None:
        query = query.limit(limit)

    result = await db.execute(query)
    return list(result.scalars().all())


async def fetch_threads_with_drifted_issue_tracking(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    limit: int | None = None,
) -> list[Thread]:
    """Return tracked threads that need reconciliation.

    Threads are reported when either their counters disagree with their issue
    rows or they carry a stale blocked flag: the canonical evaluator only
    blocks threads with a live next-unread frontier, so ``is_blocked=True`` on
    a tracked thread without a next-unread pointer is stale even when its
    counters are otherwise correct.

    Only threads already using issue tracking (``total_issues`` set) are
    considered, so old counter-based threads are never reported or migrated.
    Threads that declare a nonzero total without local rows are also left
    alone, preserving a declared series size until rows are adopted.

    Args:
        db: Database session.
        user_id: Optional owner filter for a bounded, per-user pass.
        limit: Optional maximum number of threads to return.

    Returns:
        Threads needing repair ordered by ID.
    """
    issue_stats = (
        select(
            Issue.thread_id.label("thread_id"),
            func.count().label("row_count"),
            func.count().filter(Issue.status == "unread").label("unread_count"),
        )
        .group_by(Issue.thread_id)
        .subquery()
    )
    pointer_issue = aliased(Issue)
    has_issue_rows = issue_stats.c.thread_id.is_not(None)

    counter_drift = and_(
        has_issue_rows,
        or_(
            Thread.total_issues.is_distinct_from(issue_stats.c.row_count),
            Thread.issues_remaining != issue_stats.c.unread_count,
            and_(
                issue_stats.c.unread_count > 0,
                Thread.next_unread_issue_id.is_(None),
            ),
            and_(
                issue_stats.c.unread_count == 0,
                Thread.next_unread_issue_id.is_not(None),
            ),
            and_(
                Thread.next_unread_issue_id.is_not(None),
                or_(
                    pointer_issue.status != "unread",
                    pointer_issue.thread_id != Thread.id,
                ),
            ),
        ),
    )
    # Empty tracked threads (``total_issues == 0``) and all-read threads with
    # correct counters can still hold a stale blocked flag. The canonical
    # evaluator can only block a thread with a live next-unread frontier, so
    # ``is_blocked`` with no pointer is stale regardless of the counters.
    stale_blocked_flag = and_(
        Thread.is_blocked.is_(True),
        Thread.next_unread_issue_id.is_(None),
        or_(has_issue_rows, Thread.total_issues == 0),
    )

    query = (
        select(Thread)
        .outerjoin(issue_stats, issue_stats.c.thread_id == Thread.id)
        .outerjoin(pointer_issue, pointer_issue.id == Thread.next_unread_issue_id)
        .where(Thread.total_issues.is_not(None))
        .where(or_(counter_drift, stale_blocked_flag))
        .order_by(Thread.id)
    )
    if user_id is not None:
        query = query.where(Thread.user_id == user_id)
    if limit is not None:
        query = query.limit(limit)

    result = await db.execute(query)
    return list(result.scalars().all())


class _MappingHealthRow(TypedDict):
    """Row shape for the batched mapping health query."""

    thread_id: int
    tracked_issue_count: int
    confirmed_issue_count: int
    needs_mapping_count: int
    needs_review_count: int
    metadata_missing_count: NotRequired[int]
    has_issues: bool


async def fetch_comicvine_mapping_health(
    db: AsyncSession, thread_ids: set[int]
) -> dict[int, _MappingHealthRow]:
    """Compute ComicVine mapping health for a set of threads in a single batched query.

    Derives health from stored canonical issue mappings only. No live provider calls.
    Counts are scoped to the issues represented by each thread. Threads without
    issue tracking (legacy) or without issue rows resolve to zero counts via the
    Python fill-in below, so this query only aggregates tracked threads.

    Args:
        db: Database session.
        thread_ids: Thread IDs to compute health for. Empty set returns empty mapping.

    Returns:
        Mapping of thread_id -> health row with counts and status indicators.
    """
    if not thread_ids:
        return {}

    # Get all issues for these threads with their mapping status aggregated
    # We need to count per thread:
    # - total issues (tracked_issue_count)
    # - issues with at least one confirmed ComicVine mapping (confirmed_issue_count)
    # - issues with no confirmed mapping (unresolved/candidate or no mapping at all)
    # - issues with multiple confirmed mappings or other conflicts (needs_review_count)

    # Subquery: for each issue, determine its mapping state. The per-issue
    # grain is required so that fan-out from multiple mappings on one issue
    # cannot inflate thread-level counts, and so that issues with more than
    # one confirmed mapping are detectable for review. The confirmed/comicvine
    # predicate lives in the JOIN conditions (issue #3463) so non-matching
    # mappings never fan out into per-row FILTER evaluation; counting the
    # non-null joined identity is exactly the confirmed ComicVine total.
    # The tracked-threads semi-join preserves the legacy-threads-resolve-to-
    # zero contract for every caller (see the #3384 regression test): orphan
    # issue rows on a legacy thread never leak into the queue payload.
    tracked_threads = (
        select(Thread.id)
        .where(Thread.id.in_(thread_ids))
        .where(Thread.total_issues.is_not(None))
        .subquery()
    )
    issue_mapping_state = (
        select(
            Issue.id.label("issue_id"),
            Issue.thread_id.label("thread_id"),
            func.count(ExternalIdentity.id).label("confirmed_count"),
            func.count(ExternalIdentity.id)
            .filter(
                or_(
                    func.coalesce(ExternalIdentity.metadata_json["issue_number"].as_string(), "")
                    == "",
                    func.coalesce(
                        ExternalIdentity.metadata_json["volume"]["name"].as_string(),
                        ExternalIdentity.metadata_json["volume_name"].as_string(),
                        "",
                    )
                    == "",
                )
            )
            .label("metadata_missing_count"),
        )
        .select_from(Issue)
        .where(Issue.thread_id.in_(select(tracked_threads.c.id)))
        .outerjoin(
            IssueExternalIdentityMapping,
            and_(
                IssueExternalIdentityMapping.issue_id == Issue.id,
                IssueExternalIdentityMapping.status == "confirmed",
            ),
        )
        .outerjoin(
            ExternalIdentity,
            and_(
                ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
                ExternalIdentity.provider == "comicvine",
            ),
        )
        .group_by(Issue.id, Issue.thread_id)
        .subquery()
    )

    # Aggregate per thread. This subquery already yields one row per thread,
    # so selecting from it directly is the whole query: no UNION arm and no
    # redundant outer GROUP BY pass. Threads with no rows here (legacy or
    # empty) are completed by the fill-in below with identical zero values.
    thread_aggregation = select(
        issue_mapping_state.c.thread_id,
        func.count(issue_mapping_state.c.issue_id).label("tracked_issue_count"),
        func.count()
        .filter(issue_mapping_state.c.confirmed_count > 0)
        .label("confirmed_issue_count"),
        func.count()
        .filter(issue_mapping_state.c.confirmed_count == 0)
        .label("needs_mapping_count"),
        func.count().filter(issue_mapping_state.c.confirmed_count > 1).label("needs_review_count"),
        func.count()
        .filter(issue_mapping_state.c.metadata_missing_count > 0)
        .label("metadata_missing_count"),
        (func.count(issue_mapping_state.c.issue_id) > 0).label("has_issues"),
    ).group_by(issue_mapping_state.c.thread_id)

    result = await db.execute(thread_aggregation)
    rows = result.all()

    health_map: dict[int, _MappingHealthRow] = {}
    for row in rows:
        health_map[row.thread_id] = _MappingHealthRow(
            thread_id=row.thread_id,
            tracked_issue_count=row.tracked_issue_count,
            confirmed_issue_count=row.confirmed_issue_count,
            needs_mapping_count=row.needs_mapping_count,
            needs_review_count=row.needs_review_count,
            metadata_missing_count=row.metadata_missing_count,
            has_issues=row.has_issues,
        )

    # Ensure all requested thread_ids are present (threads with no issues and issue tracking enabled)
    for tid in thread_ids:
        if tid not in health_map:
            health_map[tid] = _MappingHealthRow(
                thread_id=tid,
                tracked_issue_count=0,
                confirmed_issue_count=0,
                needs_mapping_count=0,
                needs_review_count=0,
                metadata_missing_count=0,
                has_issues=False,
            )

    return health_map


async def owned_title_exists(db: AsyncSession, user_id: int, title: str) -> bool:
    """Check whether a reader already has a thread with an exact display title.

    Args:
        db: Current transaction.
        user_id: Reader whose titles are checked.
        title: Proposed display title.

    Returns:
        Whether any thread owned by this reader uses the title.
    """
    return (
        await db.scalar(
            select(Thread.id).where(Thread.user_id == user_id, Thread.title == title).limit(1)
        )
        is not None
    )
