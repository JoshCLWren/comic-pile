"""Data access for the bounded personal creator detail API (issue #2037).

This repository owns all query construction for creator detail collections.
Every query is user-scoped to ensure that one user's creator data never leaks
to another user. Collections are bounded by a page ``limit``/``offset`` and are
ordered deterministically: recent-first for rated/read-but-unrated rows and
ComicPile queue order for upcoming rows.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.issue import Issue
from app.models.thread import Thread


#: Row shape for recent-first collections:
#: ``(issue_id, issue_number, thread_id, thread_title, status)``.
RecentCreatorIssueRow = tuple[int, str, int, str, str]

#: Row shape for upcoming collections: ``(issue_id, issue_number, thread_id,
#: thread_title, status, queue_position, issue_position)``.
UpcomingCreatorIssueRow = tuple[int, str, int, str, str, int, int]


class CreatorSummaryInputs:
    """Bounded inputs for creator summary aggregation.

    Combines issue/thread/rating data with effective rating timestamps to
    avoid repeated user event history scans.
    """

    def __init__(
        self,
        *,
        issue_ids: list[int],
        thread_ids: list[int],
        effective_ratings: dict[int, float | None],
        effective_rating_timestamps: dict[int, datetime],
    ) -> None:
        """Initialize creator summary inputs.

        Args:
            issue_ids: Local issue ids attributed to the creator.
            thread_ids: Thread ids for the attributed issues.
            effective_ratings: Mapping of issue id to its latest effective rating.
            effective_rating_timestamps: Mapping of issue id to its latest rate event timestamp.
        """
        self.issue_ids = issue_ids
        self.thread_ids = thread_ids
        self.effective_ratings = effective_ratings
        self.effective_rating_timestamps = effective_rating_timestamps


async def load_creator_summary_inputs(
    db: AsyncSession,
    *,
    user_id: int,
    creator_issue_ids: frozenset[int],
) -> CreatorSummaryInputs:
    """Load creator summary inputs with optimized timestamp reading.

    Reads owned issues, thread ids, the winning rate rating, and that event's
    timestamp as one user-scoped statement, avoiding repeated scans of the
    user's event history.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_issue_ids: Local issue ids attributed to the creator.

    Returns:
        Creator summary inputs with effective ratings and timestamps.
    """
    if not creator_issue_ids:
        return CreatorSummaryInputs(
            issue_ids=[],
            thread_ids=[],
            effective_ratings={},
            effective_rating_timestamps={},
        )
    
    result = await db.execute(
        select(
            Issue.id,
            Issue.thread_id,
            Event.rating,
            Event.timestamp,
        )
        .join(Thread, Thread.id == Issue.thread_id)
        .outerjoin(
            Event,
            (Event.issue_id == Issue.id)
            & (Event.type == "rate")
            & (Event.issue_id.is_not(None))
            & (Event.rating.is_not(None)),
        )
        .where(Thread.user_id == user_id)
        .where(Issue.id.in_(creator_issue_ids))
        .order_by(
            Issue.id,
            Event.timestamp.desc(),
            Event.id.desc(),
        )
    )
    
    issue_ids = []
    thread_ids = []
    effective_ratings = {}
    effective_rating_timestamps = {}
    
    for issue_id, thread_id, rating, timestamp in result:
        issue_ids.append(issue_id)
        thread_ids.append(thread_id)
        
        # Use the first rating we see for each issue (DISTINCT ON semantics)
        if issue_id not in effective_ratings:
            effective_ratings[issue_id] = rating
            if timestamp is not None:
                effective_rating_timestamps[issue_id] = timestamp
    
    return CreatorSummaryInputs(
        issue_ids=issue_ids,
        thread_ids=thread_ids,
        effective_ratings=effective_ratings,
        effective_rating_timestamps=effective_rating_timestamps,
    )


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


async def load_all_creator_issue_rows(
    db: AsyncSession,
    *,
    user_id: int,
    creator_issue_ids: frozenset[int],
) -> list[RecentCreatorIssueRow]:
    """Load every attributed issue row for a creator in stable issue-id order.

    The metric drilldown service (issue #3176) aggregates over the creator's
    complete attributed work so summary numbers and drilldown evidence always
    reconcile; paging the drilldown response never changes the calculation.
    Callers paginate the returned rows in Python after aggregating.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_issue_ids: Local issue ids attributed to the creator.

    Returns:
        All attributed issue rows ordered by ascending local issue id.
    """
    if not creator_issue_ids:
        return []
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
        .order_by(Issue.id.asc())
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
    "CreatorSummaryInputs",
    "load_all_creator_issue_rows",
    "load_creator_summary_inputs",
    "load_recent_creator_issue_rows",
    "load_upcoming_creator_issue_rows",
]
