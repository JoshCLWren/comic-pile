"""Data access for the bounded personal creator detail API (issue #2037).

This repository owns all query construction for creator detail collections.
Every query is user-scoped to ensure that one user's creator data never leaks
to another user. Collections are bounded by a page ``limit``/``offset`` and are
ordered deterministically: recent-first for rated/read-but-unrated rows and
ComicPile queue order for upcoming rows.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import Issue
from app.models.thread import Thread

#: Row shape for recent-first collections:
#: ``(issue_id, issue_number, thread_id, thread_title, status)``.
RecentCreatorIssueRow = tuple[int, str, int, str, str]

#: Row shape for upcoming collections: ``(issue_id, issue_number, thread_id,
#: thread_title, status, queue_position, issue_position)``.
UpcomingCreatorIssueRow = tuple[int, str, int, str, str, int, int]


async def load_recent_creator_issue_rows(
    db: AsyncSession,
    *,
    user_id: int,
    creator_issue_ids: frozenset[int],
    limit: int,
    offset: int,
) -> list[RecentCreatorIssueRow]:
    """Load a bounded page of a creator's issues ordered recent-first.

    Rows are ordered by descending local issue id so the newest owned issue
    appears first with a stable tie-breaker.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_issue_ids: Local issue ids attributed to the creator.
        limit: Max number of rows to return.
        offset: Row offset for pagination.

    Returns:
        A bounded list of recent-first issue rows.
    """
    result = await db.execute(
        select(
            Issue.id,
            Issue.issue_number,
            Issue.thread_id,
            Thread.title,
            Issue.status,
        )
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .where(Issue.id.in_(creator_issue_ids))
        .order_by(Issue.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows: list[RecentCreatorIssueRow] = [
        (int(issue_id), str(issue_number), int(thread_id), str(thread_title), str(status))
        for issue_id, issue_number, thread_id, thread_title, status in result.all()
    ]
    return rows


async def load_upcoming_creator_issue_rows(
    db: AsyncSession,
    *,
    user_id: int,
    creator_issue_ids: frozenset[int],
    limit: int,
    offset: int,
) -> list[UpcomingCreatorIssueRow]:
    """Load a bounded page of a creator's upcoming issues in queue order.

    Upcoming rows follow ComicPile's existing thread queue order and in-thread
    issue order rather than any external bibliography ordering.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_issue_ids: Local issue ids attributed to the creator.
        limit: Max number of rows to return.
        offset: Row offset for pagination.

    Returns:
        A bounded list of upcoming issue rows in queue order.
    """
    result = await db.execute(
        select(
            Issue.id,
            Issue.issue_number,
            Issue.thread_id,
            Thread.title,
            Issue.status,
            Thread.queue_position,
            Issue.position,
        )
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .where(Issue.id.in_(creator_issue_ids))
        .order_by(Thread.queue_position.asc(), Issue.position.asc(), Issue.id.asc())
        .offset(offset)
        .limit(limit)
    )
    rows: list[UpcomingCreatorIssueRow] = [
        (
            int(issue_id),
            str(issue_number),
            int(thread_id),
            str(thread_title),
            str(status),
            int(queue_position),
            int(issue_position),
        )
        for issue_id, issue_number, thread_id, thread_title, status, queue_position, issue_position
        in result.all()
    ]
    return rows


__all__ = [
    "RecentCreatorIssueRow",
    "UpcomingCreatorIssueRow",
    "load_recent_creator_issue_rows",
    "load_upcoming_creator_issue_rows",
]