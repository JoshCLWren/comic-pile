"""Data access for the bounded personal creator detail API (issue #2037).

This repository owns all query construction and persistence for creator details.
Every query is user-scoped to ensure that one user's creator data never leaks
to another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, desc, func

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.repositories.creator_summary import COMICVINE_PROVIDER


@dataclass(frozen=True)
class CreatorIssueDetail:
    """Raw data for an issue attributed to a creator.

    Attributes:
        issue_id: Local ComicPile issue ID.
        issue_number: The issue number.
        thread_id: Local ComicPile thread ID.
        thread_title: Title of the containing thread.
        status: Read/unread status.
        roles: Roles the creator held on this issue.
        effective_rating: Latest rating value, if any.
        rating_timestamp: Timestamp of the latest rating, if any.
    """
    issue_id: int
    issue_number: int
    thread_id: int
    thread_title: str
    status: str
    roles: list[str]
    effective_rating: float | None = None
    rating_timestamp: int | None = None


async def load_creator_detail_data(
    db: AsyncSession,
    user_id: int,
    creator_external_id: int,
    limit: int = 100,
    offset: int | None = None,
) -> tuple[list[tuple[int, int, int, str, str, dict]], int]:
    """Load a bounded list of issues attributed to a specific creator for a user.

    Args:
        db: Async database session.
        user_id: Authenticated user.
        creator_external_id: The external person ID to filter by.
        limit: Max number of issues to return.
        offset: Offset for pagination.

    Returns:
        A tuple of (list of rows, total count).
    """
    # Use JSONB containment to filter for the creator in SQL
    # metadata_json -> 'creator_credits' contains a list of objects where 'id' = creator_external_id
    # This is more efficient than fetching all issues and filtering in Python.
    
    # The JSON structure is [{"id": ..., "name": ..., "role": ...}, ...]
    # In PostgreSQL: metadata_json @> '{"creator_credits": [{"id": 123}]}'
    # However, since creator_external_id is an int, we construct the JSON string.
    
    filter_json = {"creator_credits": [{"id": creator_external_id}]}
    
    count_stmt = (
        select(sqlalchemy.func.count(Issue.id))
        .join(Thread, Thread.id == Issue.thread_id)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(Thread.user_id == user_id)
        .where(IssueExternalIdentityMapping.status == "confirmed")
        .where(ExternalIdentity.provider == COMICVINE_PROVIDER)
        .where(ExternalIdentity.metadata_json.contains(filter_json))
    )
    
    total_count = await db.scalar(count_stmt) or 0
    
    stmt = (
        select(
            Issue.id,
            Issue.issue_number,
            Issue.thread_id,
            Thread.title,
            Issue.status,
            ExternalIdentity.metadata_json,
        )
        .join(Thread, Thread.id == Issue.thread_id)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(Thread.user_id == user_id)
        .where(IssueExternalIdentityMapping.status == "confirmed")
        .where(ExternalIdentity.provider == COMICVINE_PROVIDER)
        .where(ExternalIdentity.metadata_json.contains(filter_json))
        .order_by(desc(Issue.id))
    )
    
    if offset is not None:
        stmt = stmt.offset(offset)
    stmt = stmt.limit(limit)
    
    result = await db.execute(stmt)
    rows = result.all()
    
    return rows, total_count
