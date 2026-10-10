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


def _extract_publisher_name(metadata_json: dict[str, object] | None) -> str | None:
    """Extract publisher name from metadata JSON."""
    if not metadata_json:
        return None
    publisher = metadata_json.get("publisher")
    if isinstance(publisher, dict):
        return publisher.get("name")
    return publisher if isinstance(publisher, str) else None


async def get_series_with_issues(
    db: AsyncSession,
    *,
    provider: str,
    series_external_id: str,
    user_id: int,
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """Get series information and related issues for preview mapping.
    
    Args:
        db: Database session.
        provider: Provider name (e.g., "comicvine").
        series_external_id: Provider-specific series identifier.
        user_id: User ID for authorization.
        
    Returns:
        Tuple of (series_info, issues_with_mappings) where series_info is None
        if not found, and issues_with_mappings contains issue data with mapping status.
    """
    from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping, ThreadExternalSeriesMapping
    from app.models.issue import Issue
    from app.models.thread import Thread
    
    # First try to find the series in the local catalog
    series_result = await db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.entity_type == "series",
            ExternalIdentity.provider == provider.strip().lower(),
            ExternalIdentity.external_id == series_external_id,
        )
    )
    series_identity = series_result.scalar_one_or_none()
    
    if series_identity is None:
        return None, []
    
    # Get issues that belong to this series from the catalog.
    # Filter threads to those with confirmed series mappings for the specific series.
    issues_result = await db.execute(
        select(ExternalIdentity, IssueExternalIdentityMapping, Issue, Thread, ThreadExternalSeriesMapping)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
        )
        .join(
            Issue,
            Issue.id == IssueExternalIdentityMapping.issue_id,
        )
        .join(
            Thread,
            Thread.id == Issue.thread_id,
        )
        .join(
            ThreadExternalSeriesMapping,
            ThreadExternalSeriesMapping.thread_id == Thread.id,
        )
        .where(
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.provider == provider.strip().lower(),
            Thread.user_id == user_id,
            ThreadExternalSeriesMapping.external_identity_id == series_identity.id,
            ThreadExternalSeriesMapping.status == "confirmed",
        )
    )

    issues_with_mappings = []
    for issue_identity, issue_mapping, issue, thread, _tsm in issues_result:
        issue_info = {
            "issue_id": issue_mapping.issue_id,
            "issue_number": issue.issue_number,
            "title": issue_identity.metadata_json.get("name") if issue_identity.metadata_json else None,
            "thread_id": thread.id,
            "thread_title": thread.title,
            "current_mapping_status": issue_mapping.status,
            "provider": issue_identity.provider,
            "external_id": issue_identity.external_id,
            "confidence": issue_mapping.confidence,
            "classification": "unresolved",
        }
        issues_with_mappings.append(issue_info)
    
    series_info = {
        "id": series_identity.external_id,
        "name": series_identity.metadata_json.get("name") if series_identity.metadata_json else None,
        "publisher": _extract_publisher_name(series_identity.metadata_json),
        "start_year": series_identity.metadata_json.get("start_year"),
        "count_of_issues": series_identity.metadata_json.get("count_of_issues"),
        "site_detail_url": series_identity.external_url,
        "image": series_identity.metadata_json.get("image") if series_identity.metadata_json else None,
    }
    
    return series_info, issues_with_mappings


async def find_owned_thread_for_provider_series(
    db: AsyncSession,
    *,
    user_id: int,
    provider: str,
    series_external_id: str,
) -> int | None:
    """Find an owned thread already confirmed against one provider series.

    Source-driven series imports retry after partial provider failures, so the
    import path needs to recognize a thread it already created for the same
    provider volume instead of creating a second copy of the same series.

    Args:
        db: Async database session.
        user_id: Owner whose threads are eligible for reuse.
        provider: Provider name (e.g. ``comicvine``).
        series_external_id: Stable provider series/volume identifier.

    Returns:
        The owned thread ID carrying a confirmed mapping to that series, or
        ``None`` when no such thread exists.
    """
    from app.models.external_identity import ThreadExternalSeriesMapping
    from app.models.thread import Thread

    thread_id = await db.scalar(
        select(ThreadExternalSeriesMapping.thread_id)
        .join(Thread, Thread.id == ThreadExternalSeriesMapping.thread_id)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
        )
        .where(
            Thread.user_id == user_id,
            ThreadExternalSeriesMapping.status == "confirmed",
            ExternalIdentity.entity_type == "series",
            ExternalIdentity.provider == provider.strip().lower(),
            ExternalIdentity.external_id == series_external_id.strip(),
        )
        .order_by(ThreadExternalSeriesMapping.id)
        .limit(1)
    )
    return thread_id


async def has_confirmed_series_mapping_for_origin(
    db: AsyncSession,
    *,
    provider: str,
    series_external_id: str | None,
    origin_issue_id: int,
    origin_issue_thread_id: int | None,
) -> bool:
    """Return whether the origin issue carries confirmed evidence for one provider series.

    Issue-level corrections do not store the provider on the mapping row, so the provider
    filter is resolved through the mapped external identity. Both a confirmed issue identity
    for ``provider`` and a confirmed thread-series mapping to ``series_external_id`` count as
    confirmed evidence; thread membership alone does not.

    Args:
        db: Database session.
        provider: Provider name (e.g., "comicvine").
        series_external_id: Selected provider series external id.
        origin_issue_id: Anchor ComicPile issue id.
        origin_issue_thread_id: Anchor issue's thread id, or ``None`` when unknown.

    Returns:
        ``True`` when confirmed provider-series evidence exists for the origin issue.
    """
    from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping, ThreadExternalSeriesMapping

    normalized_provider = provider.strip().lower()

    issue_identity_result = await db.execute(
        select(IssueExternalIdentityMapping)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(
            IssueExternalIdentityMapping.issue_id == origin_issue_id,
            IssueExternalIdentityMapping.status == "confirmed",
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.provider == normalized_provider,
        )
    )
    if issue_identity_result.scalars().first() is not None:
        return True

    if series_external_id is None or origin_issue_thread_id is None:
        return False

    series_identity_result = await db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.entity_type == "series",
            ExternalIdentity.provider == normalized_provider,
            ExternalIdentity.external_id == series_external_id,
        )
    )
    series_identity = series_identity_result.scalars().first()
    if series_identity is None:
        return False

    thread_mapping_result = await db.execute(
        select(ThreadExternalSeriesMapping).where(
            ThreadExternalSeriesMapping.thread_id == origin_issue_thread_id,
            ThreadExternalSeriesMapping.external_identity_id == series_identity.id,
            ThreadExternalSeriesMapping.status == "confirmed",
        )
    )
    return thread_mapping_result.scalars().first() is not None


async def get_thread_issues_for_sibling_scope(
    db: AsyncSession,
    *,
    thread_id: int,
    user_id: int,
    exclude_issue_id: int,
) -> list[dict[str, object]]:
    """Return the anchor thread's remaining issues with their current mapping state.

    Sibling scoping (issue #2769) reuses the series preview the user already triggered from a
    corrected issue. Only issues the caller owns are returned, and the anchor issue itself is
    excluded because the preview reports it through its own confirmed mapping row.

    Args:
        db: Database session.
        thread_id: Anchor issue's thread id.
        user_id: User ID for ownership filtering.
        exclude_issue_id: Anchor issue id to omit from the sibling scope.

    Returns:
        Plain row dicts matching the preview candidate-row shape. An issue without any mapping
        row reports ``current_mapping_status``, ``provider``, and ``external_id`` as ``None``.
    """
    from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
    from app.models.issue import Issue
    from app.models.thread import Thread

    result = await db.execute(
        select(Issue, Thread, IssueExternalIdentityMapping, ExternalIdentity)
        .join(Thread, Thread.id == Issue.thread_id)
        .outerjoin(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .outerjoin(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(
            Issue.thread_id == thread_id,
            Thread.user_id == user_id,
            Issue.id != exclude_issue_id,
        )
        .order_by(Issue.position, Issue.id)
    )

    rows: list[dict[str, object]] = []
    for issue, thread, mapping, identity in result:
        rows.append(
            {
                "issue_id": issue.id,
                "issue_number": issue.issue_number,
                "title": identity.metadata_json.get("name") if identity and identity.metadata_json else None,
                "thread_id": thread.id,
                "thread_title": thread.title,
                "current_mapping_status": mapping.status if mapping is not None else None,
                "provider": identity.provider if identity is not None else None,
                "external_id": identity.external_id if identity is not None else None,
                "confidence": mapping.confidence if mapping is not None else None,
            }
        )
    return rows


async def get_issue_by_id(
    db: AsyncSession,
    issue_id: int,
    user_id: int,
) -> dict[str, object] | None:
    """Get issue information by ID with thread context.

    Args:
        db: Database session.
        issue_id: ComicPile issue ID.
        user_id: User ID for authorization.

    Returns:
        Issue information dict or None if not found.
    """
    from app.models.issue import Issue
    from app.models.thread import Thread
    from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping

    issue_result = await db.execute(
        select(Issue, Thread, ExternalIdentity, IssueExternalIdentityMapping)
        .join(Thread, Thread.id == Issue.thread_id)
        .outerjoin(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .outerjoin(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(
            Issue.id == issue_id,
            Thread.user_id == user_id,
        )
    )

    issue_row = issue_result.first()
    if not issue_row:
        return None

    issue, thread, identity, mapping = issue_row

    return {
        "issue_id": issue.id,
        "issue_number": issue.issue_number,
        "title": identity.metadata_json.get("name") if identity and identity.metadata_json else None,
        "thread_id": thread.id,
        "thread_title": thread.title,
        "current_mapping_status": mapping.status if mapping is not None else None,
        "provider": identity.provider if identity is not None else None,
        "external_id": identity.external_id if identity is not None else None,
        "confidence": mapping.confidence if mapping is not None else None,
    }
