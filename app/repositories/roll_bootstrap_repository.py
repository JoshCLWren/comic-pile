"""Bounded query construction for the v1 Roll bootstrap endpoint (issue #3375).

``GET /api/v1/roll/bootstrap`` used to issue up to eleven sequential ``execute``
round trips per request: the roll pool, the snoozed summary, the skipped
summary, the blocked count, the blocked detail, the stale count, the stale ids,
the stale detail, every active thread, and every completed thread. Production
telemetry recorded a cold request at 1962ms against a 1000ms budget with 36
queries and 1326ms of database time (fingerprint ``86d5539183db250a``).

The cost was per-summary round trips, not per-row work: each summary re-read
overlapping columns of the same owned threads. This module collapses them into
exactly two round trips regardless of library size:

1. one owned-thread inventory fetch that supplies every derived summary; and
2. one bounded pool fetch carrying the next issue number and the correlated
   route-label aggregate.

Route labels stay inside a single correlated subquery, so no per-thread or
per-membership label query exists. Predicates that used to run in SQL
(queue position, blocked flag, snoozed/skipped membership, the stale cutoff)
are pure functions of the inventory columns and are evaluated by the calling
service in Python, which keeps their semantics identical while removing the
round trips.
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models import DependencyGroup, DependencyGroupMembership, Issue, Thread


class BootstrapThreadRow(TypedDict):
    """One owned series as stored, the source of every derived bootstrap summary."""

    id: int
    title: str
    format: str
    status: str
    queue_position: int
    is_blocked: bool
    last_activity_at: datetime | None
    created_at: datetime


class BootstrapPoolRow(TypedDict):
    """One roll-pool face joined to its next unread issue and owned route labels."""

    thread_id: int
    issue_id: int | None
    issue_number: str | None
    route_labels: list[str]


def _route_labels_subquery(user_id: int) -> ColumnElement[object]:
    """Aggregate owned route names touching a thread or its next unread issue.

    Args:
        user_id: Owner of the dependency groups.

    Returns:
        Correlated scalar subquery yielding distinct owned group names.
    """
    subq = (
        select(func.array_agg(func.distinct(DependencyGroup.name)))
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
    )
    return cast(subq, ARRAY(Text))


async def fetch_owned_thread_inventory(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[BootstrapThreadRow]:
    """Fetch every owned series once so all bootstrap summaries share one query.

    Exactly one database round trip. Every status is returned because the
    snoozed and skipped summaries address stored session ids without a status
    filter, so callers must be able to resolve them regardless of status.
    Ordering by queue position and then id keeps each derived summary stable
    and deterministic.

    Args:
        db: Async database session.
        user_id: Owner of the threads.

    Returns:
        Owned thread rows ordered by queue position, then id.
    """
    result = await db.execute(
        select(
            Thread.id,
            Thread.title,
            Thread.format,
            Thread.status,
            Thread.queue_position,
            Thread.is_blocked,
            Thread.last_activity_at,
            Thread.created_at,
        )
        .where(Thread.user_id == user_id)
        .order_by(Thread.queue_position, Thread.id)
    )
    return [
        BootstrapThreadRow(
            id=row[0],
            title=row[1],
            format=row[2],
            status=row[3],
            queue_position=row[4],
            is_blocked=row[5],
            last_activity_at=row[6],
            created_at=row[7],
        )
        for row in result.all()
    ]


async def fetch_roll_pool_rows(
    db: AsyncSession,
    *,
    user_id: int,
    thread_ids: list[int],
) -> list[BootstrapPoolRow]:
    """Fetch next-issue and route-label detail for an already-bounded pool.

    Exactly one database round trip for a non-empty pool, and no query at all
    for an empty pool. Callers pass the rollable ids they derived from the
    owned-thread inventory, so the die cap and every snoozed/skipped/blocked
    exclusion have already been applied and this query never has to re-derive
    them.

    Args:
        db: Async database session.
        user_id: Owner of the threads and route labels.
        thread_ids: Rollable thread ids, already bounded and ordered.

    Returns:
        Pool rows carrying the next unread issue and owned route labels.
    """
    if not thread_ids:
        return []

    result = await db.execute(
        select(
            Thread.id,
            Thread.next_unread_issue_id,
            Issue.issue_number,
            _route_labels_subquery(user_id).label("route_labels"),
        )
        .outerjoin(Issue, Issue.id == Thread.next_unread_issue_id)
        .where(Thread.user_id == user_id)
        .where(Thread.id.in_(thread_ids))
        .order_by(Thread.queue_position, Thread.id)
    )
    return [
        BootstrapPoolRow(
            thread_id=row[0],
            issue_id=row[1],
            issue_number=row[2],
            route_labels=list(row[3] or []),
        )
        for row in result.all()
    ]
