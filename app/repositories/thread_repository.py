"""Thread query construction and persistence.

All SQLAlchemy access for the ``Thread`` model family lives here. Functions
return ORM models or plain values; callers (services) own transactions.
"""

from datetime import datetime
from typing import TypedDict

from sqlalchemy import and_, delete, func, literal_column, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Issue, Thread
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.services.queue_pagination import QueueCursor, QueueSort, build_cursor_filter, build_sort_order


async def get_thread(db: AsyncSession, thread_id: int) -> Thread | None:
    """Return a thread by primary key without ownership filtering.

    Args:
        db: Database session.
        thread_id: Primary key of the thread.

    Returns:
        The thread, or None when it does not exist.
    """
    return await db.get(Thread, thread_id)


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
    """Return the highest queue position held by a user's threads (0 if none).

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        The maximum queue position, or 0 when the user has no threads.
    """
    result = await db.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == user_id)
        .order_by(Thread.queue_position.desc())
    )
    return result.scalar() or 0


async def fetch_stale_threads(
    db: AsyncSession,
    user_id: int,
    cutoff_date: datetime,
    snoozed_ids: list[int] | None = None,
) -> list[Thread]:
    """Fetch active, unblocked threads whose last activity predates a cutoff.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        cutoff_date: Threads last read before this instant are stale.
        snoozed_ids: Thread IDs currently snoozed in the session; these are
            excluded from the stale result.

    Returns:
        Stale threads ordered oldest activity first (nulls first).
    """
    query = (
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(False))
        .where((Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None)))
        .order_by(Thread.last_activity_at.asc().nullsfirst())
    )
    if snoozed_ids:
        query = query.where(Thread.id.not_in(snoozed_ids))
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


async def fetch_queue_page(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None,
    sort: QueueSort,
    cursor: QueueCursor | None,
    limit: int,
) -> list[Thread]:
    """Fetch one deterministic page of a user's ACTIVE threads for the queue list.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        search: Normalized case-insensitive title substring, or None.
        sort: Validated sort order key with deterministic tie-breakers.
        cursor: Decoded continuation cursor, or None for the first page.
        limit: Maximum number of threads to return.

    Returns:
        Active threads in canonical page order, at most ``limit`` rows.
    """
    query = select(Thread).where(
        Thread.user_id == user_id,
        Thread.status == "active"
    )

    if search:
        query = query.where(Thread.title.ilike(f"%{search}%"))

    # Apply deterministic sort order with tie-breakers
    for col in build_sort_order(sort):
        query = query.order_by(col)

    # Apply opaque cursor-based pagination
    if cursor is not None:
        query = query.where(build_cursor_filter(cursor))

    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def fetch_completed_page(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None,
    sort: QueueSort,
    cursor: QueueCursor | None,
    limit: int,
) -> list[Thread]:
    """Fetch one deterministic page of a user's COMPLETED threads for the finished series.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        search: Normalized case-insensitive title substring, or None.
        sort: Validated sort order key with deterministic tie-breakers.
        cursor: Decoded continuation cursor, or None for the first page.
        limit: Maximum number of threads to return.

    Returns:
        Completed threads in canonical page order, at most ``limit`` rows.

    Note:
        Callers normalize ``position`` to ``created`` before calling (completed
        threads hold no live queue positions). The shared
        :func:`build_sort_order` helper keeps the ORDER BY columns and the
        keyset cursor filter on the same contract for every sort.
    """
    query = select(Thread).where(
        Thread.user_id == user_id,
        Thread.status == "completed"
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
    return list(result.scalars().all())


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


async def fetch_threads_with_drifted_issue_tracking(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    limit: int | None = None,
) -> list[Thread]:
    """Return tracked threads whose counters disagree with their issue rows.

    Only threads already using issue tracking (``total_issues`` set) that own
    at least one issue row are considered, so old counter-based threads and
    threads still tracking a declared total without local rows are never
    reported or migrated by the reconciliation pass.

    Args:
        db: Database session.
        user_id: Optional owner filter for a bounded, per-user pass.
        limit: Optional maximum number of threads to return.

    Returns:
        Drifted threads ordered by ID.
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

    query = (
        select(Thread)
        .join(issue_stats, issue_stats.c.thread_id == Thread.id)
        .outerjoin(pointer_issue, pointer_issue.id == Thread.next_unread_issue_id)
        .where(Thread.total_issues.is_not(None))
        .where(
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
            )
        )
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
    has_issues: bool


async def fetch_comicvine_mapping_health(
    db: AsyncSession, thread_ids: set[int]
) -> dict[int, _MappingHealthRow]:
    """Compute ComicVine mapping health for a set of threads in a single batched query.

    Derives health from stored canonical issue mappings only. No live provider calls.
    Counts are scoped to the issues represented by each thread.

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

    # Subquery: for each issue, determine its mapping state
    issue_mapping_state = (
        select(
            Issue.id.label("issue_id"),
            Issue.thread_id.label("thread_id"),
            func.count()
            .filter(
                and_(
                    IssueExternalIdentityMapping.status == "confirmed",
                    ExternalIdentity.provider == "comicvine",
                )
            )
            .label("confirmed_count"),
            func.count()
            .filter(
                and_(
                    IssueExternalIdentityMapping.status.in_(["candidate", "unresolved"]),
                    ExternalIdentity.provider == "comicvine",
                )
            )
            .label("unconfirmed_count"),
        )
        .select_from(Issue)
        .outerjoin(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .outerjoin(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(Issue.thread_id.in_(thread_ids))
        .group_by(Issue.id, Issue.thread_id)
        .subquery()
    )

    # Aggregate per thread
    thread_aggregation = (
        select(
            issue_mapping_state.c.thread_id,
            func.count(issue_mapping_state.c.issue_id).label("tracked_issue_count"),
            func.count()
            .filter(issue_mapping_state.c.confirmed_count > 0)
            .label("confirmed_issue_count"),
            func.count()
            .filter(issue_mapping_state.c.confirmed_count == 0)
            .label("needs_mapping_count"),
            func.count()
            .filter(issue_mapping_state.c.confirmed_count > 1)
            .label("needs_review_count"),
            func.count(issue_mapping_state.c.issue_id).label("has_issues"),
        )
        .group_by(issue_mapping_state.c.thread_id)
        .subquery()
    )

    # Also get threads that have no issues at all (legacy or empty)
    threads_without_issues = (
        select(
            Thread.id.label("thread_id"),
            literal_column("0::bigint").label("tracked_issue_count"),
            literal_column("0::bigint").label("confirmed_issue_count"),
            literal_column("0::bigint").label("needs_mapping_count"),
            literal_column("0::bigint").label("needs_review_count"),
            literal_column("false::boolean").label("has_issues"),
        )
        .where(Thread.id.in_(thread_ids))
        .where(Thread.total_issues.is_(None))  # Legacy threads without issue tracking
    )

    # Union the two queries using select().union_all()
    combined = select(
        thread_aggregation.c.thread_id,
        thread_aggregation.c.tracked_issue_count,
        thread_aggregation.c.confirmed_issue_count,
        thread_aggregation.c.needs_mapping_count,
        thread_aggregation.c.needs_review_count,
        thread_aggregation.c.has_issues,
    ).union_all(threads_without_issues).subquery()

    # Final select
    final_query = select(
        combined.c.thread_id,
        combined.c.tracked_issue_count,
        combined.c.confirmed_issue_count,
        combined.c.needs_mapping_count,
        combined.c.needs_review_count,
        combined.c.has_issues,
    ).group_by(
        combined.c.thread_id,
        combined.c.tracked_issue_count,
        combined.c.confirmed_issue_count,
        combined.c.needs_mapping_count,
        combined.c.needs_review_count,
        combined.c.has_issues,
    )

    result = await db.execute(final_query)
    rows = result.all()

    health_map: dict[int, _MappingHealthRow] = {}
    for row in rows:
        health_map[row.thread_id] = _MappingHealthRow(
            thread_id=row.thread_id,
            tracked_issue_count=row.tracked_issue_count,
            confirmed_issue_count=row.confirmed_issue_count,
            needs_mapping_count=row.needs_mapping_count,
            needs_review_count=row.needs_review_count,
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
                has_issues=False,
            )

    return health_map
