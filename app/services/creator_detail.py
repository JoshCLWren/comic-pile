"""Service for the bounded personal creator detail API (issue #2037).

This service coordinates the aggregation of one creator's personal detail page,
reusing the rating, role, and coverage semantics from #2028 rather than
reimplementing a competing definition. Every personal aggregate is scoped
through the authenticated user's owned ComicPile issues and their confirmed
local issue metadata.

Ordering semantics:
- Rated history and read-but-unrated rows are deterministic recent-first.
- Upcoming rows follow ComicPile's existing thread queue order and in-thread
  issue order, never an external bibliography order.

Boundedness: each collection is a page (``limit``/``offset``) served by a fixed,
small number of queries regardless of library size. No per-issue/role N+1 fan-out.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.creator_detail import (
    load_latest_rating_timestamps,
    load_recent_creator_issue_rows,
    load_upcoming_creator_issue_rows,
)
from app.repositories.creator_summary import CreatorSummaryInputs, load_creator_summary_inputs
from app.schemas.creator_detail import (
    CreatorDetailResponse,
    CreatorIssueRow,
    CreatorRoleStat,
)
from app.schemas.creator_summary import (
    CreatorSummaryCoverage,
    CreatorSummaryItem,
)
from app.services.creator_summary import HEADLINE_ROLES, parse_creator_key


def _build_issue_row(
    inputs: CreatorSummaryInputs,
    *,
    creator_id: int,
    issue_id: int,
    issue_number: str,
    thread_id: int,
    thread_title: str,
    status: str,
    effective_rating: float | None,
    rating_timestamp: datetime | None,
    sort_key: str,
) -> CreatorIssueRow:
    """Build one detail row with roles resolved from the user-scoped inputs.

    Args:
        inputs: User-scoped creator summary inputs.
        creator_id: Stable external person id for the creator.
        issue_id: Local ComicPile issue ID.
        issue_number: Issue number.
        thread_id: Local ComicPile thread ID.
        thread_title: Title of the containing thread.
        status: Read/unread status.
        effective_rating: Latest effective rating for the issue, if any.
        rating_timestamp: Timestamp of the effective rating event, if any.
        sort_key: Deterministic local ordering information for the UI.

    Returns:
        A serializable creator issue row.
    """
    roles: set[str] = set()
    for credit in inputs.issue_creator_credits.get(issue_id, ()):
        if credit.external_id == creator_id:
            roles.update(credit.roles)
    return CreatorIssueRow(
        issue_id=issue_id,
        issue_number=issue_number,
        thread_id=thread_id,
        thread_title=thread_title,
        status=status,
        roles=sorted(roles),
        effective_rating=effective_rating,
        rating_timestamp=rating_timestamp,
        sort_key=sort_key,
    )


async def get_creator_detail(
    db: AsyncSession,
    user_id: int,
    creator_key: str,
    limit: int = 50,
    offset: int | None = None,
) -> CreatorDetailResponse:
    """Compute detailed personal analytics for a single creator.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_key: Canonical creator key (e.g. ``creator:12345``).
        limit: Max number of issues per collection page.
        offset: Page offset shared by all collections.

    Returns:
        The full creator detail response.

    Raises:
        ValueError: When the creator key is not canonical.
        KeyError: When the creator is not present in the user's own library.
    """
    creator_id = parse_creator_key(creator_key)
    if creator_id is None:
        raise ValueError("Invalid creator key format")
    page_offset = offset if offset is not None else 0

    inputs = await load_creator_summary_inputs(db, user_id)

    creator_issue_ids: set[int] = set()
    creator_roles_all: set[str] = set()
    display_name: str | None = None
    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            if credit.external_id != creator_id:
                continue
            creator_issue_ids.add(issue_id)
            creator_roles_all.update(credit.roles)
            if display_name is None:
                display_name = credit.display_name

    if display_name is None:
        raise KeyError(f"Creator {creator_key} not found in user's library")

    creator_id_set = frozenset(creator_issue_ids)

    # 1. Headline summary scoped to this creator, mirroring #2028 exactly:
    #    latest effective rate event wins, one issue counts at most once even
    #    for multi-role credits, and pure cover/editorial or unknown roles never
    #    feed the headline average.
    rated_ids = frozenset(
        issue_id for issue_id in creator_id_set if issue_id in inputs.effective_ratings
    )
    read_unrated_ids = frozenset(
        issue_id
        for issue_id in creator_id_set
        if inputs.owned_issues.get(issue_id) == "read" and issue_id not in inputs.effective_ratings
    )
    upcoming_ids = frozenset(
        issue_id for issue_id in creator_id_set if inputs.owned_issues.get(issue_id) == "unread"
    )

    headline_rated: list[float] = []
    for issue_id in creator_id_set:
        if issue_id not in inputs.effective_ratings:
            continue
        credits = inputs.issue_creator_credits[issue_id]
        if any(
            role in HEADLINE_ROLES
            for credit in credits
            if credit.external_id == creator_id
            for role in credit.roles
        ):
            headline_rated.append(inputs.effective_ratings[issue_id])
    ratings_count = len(headline_rated)
    average_rating = (
        round(sum(headline_rated) / ratings_count, 2) if ratings_count else None
    )

    summary = CreatorSummaryItem(
        canonical_creator_key=creator_key,
        display_name=display_name,
        normalized_roles=sorted(creator_roles_all),
        average_rating=average_rating,
        ratings_count=ratings_count,
        read_unrated_count=len(read_unrated_ids),
        upcoming_count=len(upcoming_ids),
    )

    # 2. Coverage block exactly as #2028 computes it over the owned library.
    rated_owned = frozenset(inputs.effective_ratings)
    read_unrated_owned = frozenset(
        issue_id
        for issue_id, status in inputs.owned_issues.items()
        if status == "read" and issue_id not in inputs.effective_ratings
    )
    unread_owned = frozenset(
        issue_id for issue_id, status in inputs.owned_issues.items() if status == "unread"
    )

    def _with_metadata(issue_ids: frozenset[int]) -> int:
        return sum(1 for issue_id in issue_ids if issue_id in inputs.issues_with_creator_metadata)

    rated_total = len(rated_owned)
    rated_with = _with_metadata(rated_owned)
    read_unrated_total = len(read_unrated_owned)
    read_unrated_with = _with_metadata(read_unrated_owned)
    unread_total = len(unread_owned)
    unread_with = _with_metadata(unread_owned)

    coverage = CreatorSummaryCoverage(
        rated_issues_total=rated_total,
        rated_issues_with_creator_metadata=rated_with,
        ratings_complete=rated_with >= rated_total,
        read_unrated_issues_total=read_unrated_total,
        read_unrated_issues_with_creator_metadata=read_unrated_with,
        read_unrated_complete=read_unrated_with >= read_unrated_total,
        unread_issues_total=unread_total,
        unread_issues_with_creator_metadata=unread_with,
        upcoming_complete=unread_with >= unread_total,
    )

    # 3. Role-specific statistics. Every distinct role is preserved honestly,
    #    including pure cover/editorial and unknown roles.
    role_stats: list[CreatorRoleStat] = []
    for role in sorted(creator_roles_all):
        role_issue_ids = [
            issue_id
            for issue_id in creator_id_set
            if any(
                role in credit.roles
                for credit in inputs.issue_creator_credits[issue_id]
                if credit.external_id == creator_id
            )
        ]
        role_ratings = [
            inputs.effective_ratings[issue_id]
            for issue_id in role_issue_ids
            if issue_id in inputs.effective_ratings
        ]
        role_stats.append(
            CreatorRoleStat(
                role=role,
                issue_count=len(role_issue_ids),
                average_rating=(
                    round(sum(role_ratings) / len(role_ratings), 2) if role_ratings else None
                ),
            )
        )

    # 4. Bounded collections with the ordering contract from the issue.
    rated_rows = await load_recent_creator_issue_rows(
        db,
        user_id=user_id,
        creator_issue_ids=rated_ids,
        limit=limit,
        offset=page_offset,
    )
    read_unrated_rows = await load_recent_creator_issue_rows(
        db,
        user_id=user_id,
        creator_issue_ids=read_unrated_ids,
        limit=limit,
        offset=page_offset,
    )
    upcoming_rows = await load_upcoming_creator_issue_rows(
        db,
        user_id=user_id,
        creator_issue_ids=upcoming_ids,
        limit=limit,
        offset=page_offset,
    )

    fetched_issue_ids = sorted(
        {row[0] for row in rated_rows}
        | {row[0] for row in read_unrated_rows}
        | {row[0] for row in upcoming_rows}
    )
    latest_rating_timestamps = await load_latest_rating_timestamps(
        db,
        issue_ids=fetched_issue_ids,
    )

    rated_issues = [
        _build_issue_row(
            inputs,
            creator_id=creator_id,
            issue_id=issue_id,
            issue_number=issue_number,
            thread_id=thread_id,
            thread_title=thread_title,
            status=status,
            effective_rating=inputs.effective_ratings.get(issue_id),
            rating_timestamp=latest_rating_timestamps.get(issue_id),
            sort_key=str(issue_id),
        )
        for issue_id, issue_number, thread_id, thread_title, status in rated_rows
    ]

    read_unrated_issues = [
        _build_issue_row(
            inputs,
            creator_id=creator_id,
            issue_id=issue_id,
            issue_number=issue_number,
            thread_id=thread_id,
            thread_title=thread_title,
            status=status,
            effective_rating=inputs.effective_ratings.get(issue_id),
            rating_timestamp=latest_rating_timestamps.get(issue_id),
            sort_key=str(issue_id),
        )
        for issue_id, issue_number, thread_id, thread_title, status in read_unrated_rows
    ]

    upcoming_issues = [
        _build_issue_row(
            inputs,
            creator_id=creator_id,
            issue_id=issue_id,
            issue_number=issue_number,
            thread_id=thread_id,
            thread_title=thread_title,
            status=status,
            effective_rating=inputs.effective_ratings.get(issue_id),
            rating_timestamp=latest_rating_timestamps.get(issue_id),
            sort_key=f"{queue_position:07d}:{issue_position:07d}:{issue_id}",
        )
        for issue_id, issue_number, thread_id, thread_title, status, queue_position, issue_position
        in upcoming_rows
    ]

    has_next_page = (
        len(rated_ids) > page_offset + len(rated_rows)
        or len(read_unrated_ids) > page_offset + len(read_unrated_rows)
        or len(upcoming_ids) > page_offset + len(upcoming_rows)
    )
    next_cursor = str(page_offset + limit) if has_next_page else None

    return CreatorDetailResponse(
        summary=summary,
        coverage=coverage,
        role_stats=role_stats,
        rated_issues=rated_issues,
        read_unrated_issues=read_unrated_issues,
        upcoming_issues=upcoming_issues,
        next_cursor=next_cursor,
    )


__all__ = [
    "get_creator_detail",
]