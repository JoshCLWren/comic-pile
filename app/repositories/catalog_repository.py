"""Catalog query construction and persistence.

All SQLAlchemy access for the ``ExternalIdentity`` model lives here. Functions
return ORM models or plain rows/tuples; callers (services) own transaction
boundaries.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import ExternalIdentity

if TYPE_CHECKING:
    from app.models.external_identity import ThreadExternalSeriesMapping, IssueExternalIdentityMapping


async def search_catalog_series(
    db: AsyncSession,
    *,
    search: str | None = None,
    provider: str = "comicvine",
    limit: int = 50,
) -> list[ExternalIdentity]:
    """Search for canonical series in the shared catalog.

    Args:
        db: Database session.
        search: Optional search term to match against series external_id.
        provider: Filter by provider name (default: comicvine).
        limit: Maximum number of results to return (hard capped at 50).

    Returns:
        List of matching external identities for series.
    """
    query = select(ExternalIdentity).where(
        ExternalIdentity.entity_type == "series",
        ExternalIdentity.provider == provider.strip().lower(),
    )

    if search:
        normalized = search.strip().lower()
        query = query.where(ExternalIdentity.external_id.ilike(f"%{normalized}%"))

    # Apply hard limit
    query = query.limit(limit)
    
    result = await db.execute(query)
    return list(result.scalars().unique().all())


async def search_catalog_issues(
    db: AsyncSession,
    *,
    search: str | None = None,
    provider: str = "comicvine",
    series_external_id: str | None = None,
    limit: int = 50,
) -> list[ExternalIdentity]:
    """Search for canonical issues in the shared catalog.

    Args:
        db: Database session.
        search: Optional search term to match against issue external_id.
        provider: Filter by provider name (default: comicvine).
        series_external_id: Filter by series external_id to scope the search.
        limit: Maximum number of results to return (hard capped at 50).

    Returns:
        List of matching external identities for issues.
    """
    query = select(ExternalIdentity).where(
        ExternalIdentity.entity_type == "issue",
        ExternalIdentity.provider == provider.strip().lower(),
    )

    # If series_external_id is provided, filter by series first
    if series_external_id:
        series_result = await db.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.entity_type == "series",
                ExternalIdentity.external_id == series_external_id,
            )
        )
        series_identity = series_result.scalar_one_or_none()
        if series_identity is None:
            return []

    if search:
        normalized = search.strip().lower()
        query = query.where(ExternalIdentity.external_id.ilike(f"%{normalized}%"))

    # Apply hard limit
    query = query.limit(limit)
    
    result = await db.execute(query)
    return list(result.scalars().unique().all())


async def list_series_mappings(
    db: AsyncSession,
    *,
    thread_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[ThreadExternalSeriesMapping]:
    """List thread-series mappings.

    Args:
        db: Database session.
        thread_id: Optional filter by thread ID.
        status: Optional filter by mapping status.
        limit: Maximum number of results to return.

    Returns:
        List of thread-series mappings.
    """
    from app.models.external_identity import ThreadExternalSeriesMapping
    
    query = select(ThreadExternalSeriesMapping)

    if thread_id is not None:
        query = query.where(ThreadExternalSeriesMapping.thread_id == thread_id)

    if status is not None:
        query = query.where(ThreadExternalSeriesMapping.status == status)

    query = query.order_by(ThreadExternalSeriesMapping.created_at.desc())
    query = query.limit(limit)
    
    result = await db.execute(query)
    return list(result.scalars().all())


async def list_issue_mappings(
    db: AsyncSession,
    *,
    issue_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[IssueExternalIdentityMapping]:
    """List issue-external identity mappings.

    Args:
        db: Database session.
        issue_id: Optional filter by issue ID.
        status: Optional filter by mapping status.
        limit: Maximum number of results to return.

    Returns:
        List of issue-external identity mappings.
    """
    from app.models.external_identity import IssueExternalIdentityMapping
    
    query = select(IssueExternalIdentityMapping)

    if issue_id is not None:
        query = query.where(IssueExternalIdentityMapping.issue_id == issue_id)

    if status is not None:
        query = query.where(IssueExternalIdentityMapping.status == status)

    query = query.order_by(IssueExternalIdentityMapping.created_at.desc())
    query = query.limit(limit)
    
    result = await db.execute(query)
    return list(result.scalars().all())
