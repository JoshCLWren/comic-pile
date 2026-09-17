"""Bounded personal creator detail aggregation (issue #2037).

This service derives the detailed creator information needed for the creator
detail page from one authenticated request. Every detail is scoped through the
authenticated user's owned ComicPile issues and their confirmed local issue
metadata. No ComicVine call and no materialized/precomputed tables are involved.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func, select

from app.models.issue import Issue
from app.models.rating import Rating
from app.models.thread import Thread
from app.models.user import User
from app.repositories.creator_summary import (
    CreatorSummaryInputs,
    load_creator_summary_inputs,
)
from app.schemas.creator_detail import (
    CreatorDetailCoverage,
    CreatorDetailResponse,
    CreatorRoleStats,
    ReadUnratedIssue,
    RatedIssue,
    UpcomingIssue,
)


def parse_creator_key(key: str) -> int | None:
    """Parse a canonical creator key into the stable external person id.

    Canonical keys are ``creator:<external-person-id>`` (issue #2036). Any
    other shape (role-scoped taste keys, display-name-derived keys, malformed
    input) parses to ``None`` and is never guessed into an identity.

    Args:
        key: Canonical serialized creator key.

    Returns:
        The stable external person id, or ``None`` for non-canonical keys.
    """
    parts = key.split(":")
    if len(parts) != 2 or parts[0] != "creator" or not parts[1].isdigit():
        return None
    return int(parts[1])


async def get_creator_detail(
    db: AsyncSession,
    user_id: int,
    creator_key: str,
    page_token: str | None = None,
    page_size: int = 20,
) -> CreatorDetailResponse:
    """Compute detailed creator information for the requested creator key.

    Only creator keys visible in the authenticated user's own confirmed issue
    metadata are returned; unknown or foreign keys result in a 404 response.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_key: Canonical creator key to retrieve details for.
        page_token: Token for pagination (optional).
        page_size: Maximum number of items per page (default 20).

    Returns:
        The creator detail response with paginated results.

    Raises:
        ValueError: When the creator key is invalid or not found.
    """
    creator_id = parse_creator_key(creator_key)
    if creator_id is None:
        raise ValueError(f"Invalid creator key: {creator_key}")

    # Load the same inputs as the summary service
    inputs = await load_creator_summary_inputs(db, user_id)

    # Check if this creator exists in the user's library
    creator_exists = any(
        credit.external_id == creator_id
        for credits in inputs.issue_creator_credits.values()
        for credit in credits
    )
    if not creator_exists:
        raise ValueError(f"Creator {creator_key} not found in your library")

    # Get basic stats (reusing logic from summary service)
    creator_issues = set()
    creator_headline_issues = set()
    creator_roles = set()
    creator_name = ""
    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            if credit.external_id == creator_id:
                creator_issues.add(issue_id)
                creator_name = credit.display_name
                creator_roles.update(credit.roles)
                if any(role in inputs.HEADLINE_ROLES for role in credit.roles):
                    creator_headline_issues.add(issue_id)

    # Calculate basic counts
    rated_issue_ids = [
        issue_id
        for issue_id in creator_issues
        if issue_id in inputs.effective_ratings and issue_id in creator_headline_issues
    ]
    ratings_count = len(rated_issue_ids)
    average_rating = (
        round(sum(inputs.effective_ratings[issue_id] for issue_id in rated_issue_ids) / ratings_count, 2)
        if ratings_count
        else None
    )

    read_unrated_issue_ids = [
        issue_id
        for issue_id in creator_issues
        if inputs.owned_issues.get(issue_id) == "read"
        and issue_id not in inputs.effective_ratings
    ]
    read_unrated_count = len(read_unrated_issue_ids)

    upcoming_issue_ids = [
        issue_id for issue_id in creator_issues if inputs.owned_issues.get(issue_id) == "unread"
    ]
    upcoming_count = len(upcoming_issue_ids)

    # Calculate role-specific stats
    role_stats: list[CreatorRoleStats] = []
    for role in sorted(creator_roles):
        role_rated_issues = [
            issue_id
            for issue_id in creator_issues
            if issue_id in inputs.effective_ratings
            and any(r == role for r in inputs.issue_creator_credits[issue_id][0].roles)
        ]
        role_rated_count = len(role_rated_issues)
        role_average_rating = (
            round(
                sum(inputs.effective_ratings[issue_id] for issue_id in role_rated_issues) / role_rated_count,
                2,
            )
            if role_rated_count
            else None
        )
        role_upcoming_count = sum(
            1
            for issue_id in creator_issues
            if inputs.owned_issues.get(issue_id) == "unread"
            and any(r == role for r in inputs.issue_creator_credits[issue_id][0].roles)
        )
        role_stats.append(
            CreatorRoleStats(
                role=role,
                average_rating=role_average_rating,
                rated_count=role_rated_count,
                upcoming_count=role_upcoming_count,
            )
        )

    # Build coverage information
    coverage = CreatorDetailCoverage(
        rated_issues_total=len(rated_issue_ids),
        upcoming_issues_total=len(upcoming_issue_ids),
        read_unrated_issues_total=len(read_unrated_issue_ids),
    )

    # Fetch detailed issue information with pagination
    rated_issues = await _fetch_rated_issues(
        db, user_id, creator_id, rated_issue_ids, page_token, page_size
    )
    upcoming_issues = await _fetch_upcoming_issues(
        db, user_id, creator_id, upcoming_issue_ids, page_token, page_size
    )
    read_unrated_issues = await _fetch_read_unrated_issues(
        db, user_id, creator_id, read_unrated_issue_ids, page_token, page_size
    )

    return CreatorDetailResponse(
        display_name=creator_name,
        average_rating=average_rating,
        ratings_count=ratings_count,
        read_unrated_count=read_unrated_count,
        upcoming_count=upcoming_count,
        ratings_complete=coverage.rated_issues_total == coverage.rated_issues_total,
        upcoming_complete=coverage.upcoming_issues_total == coverage.upcoming_issues_total,
        role_stats=role_stats,
        rated_issues=rated_issues,
        upcoming_issues=upcoming_issues,
        read_unrated_issues=read_unrated_issues,
    )


async def _fetch_rated_issues(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
    rated_issue_ids: list[int],
    page_token: str | None,
    page_size: int,
) -> list[RatedIssue]:
    """Fetch rated issues for a creator with pagination."""
    if not rated_issue_ids:
        return []

    # Apply pagination
    query = select(Issue, Thread, Rating).where(
        Issue.id.in_(rated_issue_ids),
        Thread.user_id == user_id,
        Thread.id == Issue.thread_id,
        Rating.issue_id == Issue.id,
    )

    if page_token:
        # Simple pagination by ID - in a real implementation you'd want cursor-based pagination
        try:
            min_id = int(page_token)
            query = query.where(Issue.id < min_id)
        except ValueError:
            pass

    query = query.order_by(Rating.created_at.desc(), Issue.id.desc()).limit(page_size + 1)
    result = await db.execute(query)
    rows = result.fetchall()

    issues = []
    for issue, thread, rating in rows:
        issues.append(
            RatedIssue(
                thread_id=thread.id,
                thread_title=thread.title,
                issue_number=issue.issue_number,
                creator_roles=[
                    role
                    for credit in inputs.issue_creator_credits[issue.id]
                    if credit.external_id == creator_id
                    for role in credit.roles
                ],
                effective_rating=rating.rating,
                rated_at=rating.created_at.isoformat() if rating.created_at else None,
            )
        )

    # Check if there are more results
    if len(issues) > page_size:
        issues = issues[:page_size]
        # Set page token for next page (using the last issue ID)
        issues[-1].page_token = str(issues[-1].thread_id)

    return issues


async def _fetch_upcoming_issues(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
    upcoming_issue_ids: list[int],
    page_token: str | None,
    page_size: int,
) -> list[UpcomingIssue]:
    """Fetch upcoming issues for a creator with pagination."""
    if not upcoming_issue_ids:
        return []

    # Apply pagination
    query = select(Issue, Thread).where(
        Issue.id.in_(upcoming_issue_ids),
        Thread.user_id == user_id,
        Thread.id == Issue.thread_id,
    )

    if page_token:
        # Simple pagination by ID - in a real implementation you'd want cursor-based pagination
        try:
            min_id = int(page_token)
            query = query.where(Issue.id < min_id)
        except ValueError:
            pass

    query = query.order_by(Thread.queue_position, Issue.id).limit(page_size + 1)
    result = await db.execute(query)
    rows = result.fetchall()

    issues = []
    for issue, thread in rows:
        issues.append(
            UpcomingIssue(
                thread_id=thread.id,
                thread_title=thread.title,
                issue_number=issue.issue_number,
                creator_roles=[
                    role
                    for credit in inputs.issue_creator_credits[issue.id]
                    if credit.external_id == creator_id
                    for role in credit.roles
                ],
                queue_position=thread.queue_position,
            )
        )

    # Check if there are more results
    if len(issues) > page_size:
        issues = issues[:page_size]
        # Set page token for next page (using the last issue ID)
        issues[-1].page_token = str(issues[-1].thread_id)

    return issues


async def _fetch_read_unrated_issues(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
    read_unrated_issue_ids: list[int],
    page_token: str | None,
    page_size: int,
) -> list[ReadUnratedIssue]:
    """Fetch read but unrated issues for a creator with pagination."""
    if not read_unrated_issue_ids:
        return []

    # Apply pagination
    query = select(Issue, Thread).where(
        Issue.id.in_(read_unrated_issue_ids),
        Thread.user_id == user_id,
        Thread.id == Issue.thread_id,
    )

    if page_token:
        # Simple pagination by ID - in a real implementation you'd want cursor-based pagination
        try:
            min_id = int(page_token)
            query = query.where(Issue.id < min_id)
        except ValueError:
            pass

    query = query.order_by(Issue.read_at.desc(), Issue.id.desc()).limit(page_size + 1)
    result = await db.execute(query)
    rows = result.fetchall()

    issues = []
    for issue, thread in rows:
        issues.append(
            ReadUnratedIssue(
                thread_id=thread.id,
                thread_title=thread.title,
                issue_number=issue.issue_number,
                creator_roles=[
                    role
                    for credit in inputs.issue_creator_credits[issue.id]
                    if credit.external_id == creator_id
                    for role in credit.roles
                ],
                read_at=issue.read_at.isoformat() if issue.read_at else None,
            )
        )

    # Check if there are more results
    if len(issues) > page_size:
        issues = issues[:page_size]
        # Set page token for next page (using the last issue ID)
        issues[-1].page_token = str(issues[-1].thread_id)

    return issues


__all__ = [
    "get_creator_detail",
    "parse_creator_key",
]
