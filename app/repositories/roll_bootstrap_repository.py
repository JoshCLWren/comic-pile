"""Bounded read-model queries for ``GET /api/v1/roll/bootstrap`` (issue #3375).

The bootstrap endpoint historically issued separate count, id-list, and
detail round trips for every summary family (blocked, stale, completed,
snoozed, skipped). A production cold request recorded 36 sequential queries
and 1326 ms of DB time against a 1000 ms route budget. This module issues
one round trip per summary family with identical filters:

- one pool query with the correlated route-label subquery;
- one session-scope summary query covering both snoozed and skipped IDs;
- one blocked query whose windowed ``count(*) OVER ()`` replaces the
  separate ``SELECT count(*)`` round trip (the window is evaluated before
  ``LIMIT``, so the total stays complete while the row list stays bounded);
- one stale-candidate query returning full rows, replacing the former
  count + id-list + detail triple;
- one library query covering both ``active`` and ``completed`` statuses,
  partitioned by the caller.

Functions return plain ``NamedTuple`` rows; services and routers own
response assembly and transaction boundaries.
"""

from datetime import datetime
from typing import NamedTuple

from sqlalchemy import Text, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DependencyGroup, DependencyGroupMembership, Issue, Thread


class RollPoolRow(NamedTuple):
    """One bounded roll-pool candidate with its optional route labels."""

    thread_id: int
    title: str
    format: str
    issue_id: int | None
    issue_number: str | None
    route_labels: tuple[str, ...]


class ThreadSummaryRow(NamedTuple):
    """One lightweight thread summary for a session-scope summary list."""

    thread_id: int
    title: str
    format: str


class BlockedSummaryRow(NamedTuple):
    """One bounded blocked-thread summary plus the complete blocked total."""

    thread_id: int
    title: str
    format: str
    last_activity_at: datetime | None
    blocked_total: int


class StaleCandidateRow(NamedTuple):
    """One stale-thread candidate with the fields the summary card renders."""

    thread_id: int
    title: str
    format: str
    last_activity_at: datetime | None


class LibraryThreadRow(NamedTuple):
    """One active or completed thread row used for exclusion transparency."""

    thread_id: int
    title: str
    format: str
    queue_position: int
    is_blocked: bool
    status: str


async def fetch_roll_pool_rows(
    db: AsyncSession,
    *,
    user_id: int,
    die_size: int,
    excluded_ids: list[int],
) -> list[RollPoolRow]:
    """Return the bounded roll pool for a user in a single round trip.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        die_size: Current die size bounding the pool.
        excluded_ids: Session-scope snoozed and skipped thread IDs to omit.

    Returns:
        Pool rows ordered by queue position, at most ``die_size`` long.
    """
    route_labels_subq = (
        select(
            func.array_agg(func.distinct(DependencyGroup.name)),
        )
        .select_from(DependencyGroupMembership)
        .join(DependencyGroup, DependencyGroup.id == DependencyGroupMembership.group_id)
        .where(
            or_(
                DependencyGroupMembership.thread_id == Thread.id,
                DependencyGroupMembership.issue_id == Thread.next_unread_issue_id,
            ),
            DependencyGroup.user_id == user_id,
        )
        .correlate(Thread)
        .scalar_subquery()
        .cast(ARRAY(Text))
    )

    pool_query = (
        select(
            Thread.id,
            Thread.title,
            Thread.format,
            Thread.next_unread_issue_id.label("issue_id"),
            Issue.issue_number,
            route_labels_subq.label("route_labels"),
        )
        .outerjoin(Issue, Issue.id == Thread.next_unread_issue_id)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .where(Thread.is_blocked.is_(False))
        .order_by(Thread.queue_position)
        .limit(die_size)
    )
    if excluded_ids:
        pool_query = pool_query.where(Thread.id.not_in(excluded_ids))

    result = await db.execute(pool_query)
    return [
        RollPoolRow(
            thread_id=row.id,
            title=row.title,
            format=row.format,
            issue_id=row.issue_id,
            issue_number=row.issue_number,
            route_labels=tuple(row.route_labels or ()),
        )
        for row in result.all()
    ]


async def fetch_session_scope_summary_rows(
    db: AsyncSession,
    *,
    user_id: int,
    thread_ids: list[int],
) -> list[ThreadSummaryRow]:
    """Return summaries for session-scope snoozed and skipped thread IDs.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        thread_ids: Distinct snoozed and skipped thread IDs to resolve.

    Returns:
        Summary rows for the owned subset of ``thread_ids``.
    """
    if not thread_ids:
        return []
    result = await db.execute(
        select(Thread.id, Thread.title, Thread.format)
        .where(Thread.user_id == user_id)
        .where(Thread.id.in_(thread_ids))
    )
    return [
        ThreadSummaryRow(
            thread_id=row.id,
            title=row.title,
            format=row.format,
        )
        for row in result.all()
    ]


async def fetch_blocked_summary_rows(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int,
) -> list[BlockedSummaryRow]:
    """Return bounded blocked summaries with the complete blocked total.

    The windowed count is evaluated before ``LIMIT``, so ``blocked_total``
    remains the full active-blocked count while the row list stays bounded.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        limit: Maximum blocked summary rows to return.

    Returns:
        Blocked rows ordered by queue position, each carrying the total.
    """
    result = await db.execute(
        select(
            Thread.id,
            Thread.title,
            Thread.format,
            Thread.last_activity_at,
            func.count().over().label("blocked_total"),
        )
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(True))
        .order_by(Thread.queue_position)
        .limit(limit)
    )
    return [
        BlockedSummaryRow(
            thread_id=row.id,
            title=row.title,
            format=row.format,
            last_activity_at=row.last_activity_at,
            blocked_total=int(row.blocked_total),
        )
        for row in result.all()
    ]


async def fetch_stale_candidate_rows(
    db: AsyncSession,
    *,
    user_id: int,
    stale_cutoff: datetime,
    excluded_ids: list[int],
) -> list[StaleCandidateRow]:
    """Return every stale candidate row in one round trip.

    Replaces the former ``SELECT count(*)`` + id-list + per-chosen-id detail
    triple: the row count is the stale total and any row can be chosen for
    the summary card without a follow-up query.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        stale_cutoff: Threads with effective activity before this instant are stale.
        excluded_ids: Session-scope snoozed thread IDs to omit.

    Returns:
        Stale candidate rows in unspecified order.
    """
    effective_activity = func.coalesce(Thread.last_activity_at, Thread.created_at)
    stale_query = (
        select(Thread.id, Thread.title, Thread.format, Thread.last_activity_at)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(False))
        .where(effective_activity < stale_cutoff)
    )
    if excluded_ids:
        stale_query = stale_query.where(Thread.id.not_in(excluded_ids))

    result = await db.execute(stale_query)
    return [
        StaleCandidateRow(
            thread_id=row.id,
            title=row.title,
            format=row.format,
            last_activity_at=row.last_activity_at,
        )
        for row in result.all()
    ]


async def fetch_exclusion_library_rows(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[LibraryThreadRow]:
    """Return active and completed thread rows for exclusion transparency.

    One query replaces the former separate active-list and completed-list
    round trips; the caller partitions by ``status``.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        Active and completed rows ordered by queue position.
    """
    result = await db.execute(
        select(
            Thread.id,
            Thread.title,
            Thread.format,
            Thread.queue_position,
            Thread.is_blocked,
            Thread.status,
        )
        .where(Thread.user_id == user_id)
        .where(Thread.status.in_(("active", "completed")))
        .order_by(Thread.queue_position)
    )
    return [
        LibraryThreadRow(
            thread_id=row.id,
            title=row.title,
            format=row.format,
            queue_position=row.queue_position,
            is_blocked=row.is_blocked,
            status=row.status,
        )
        for row in result.all()
    ]
