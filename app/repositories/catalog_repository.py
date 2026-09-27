"""Catalog query construction and persistence.

All SQLAlchemy access for the ``ExternalIdentity`` model lives here. Functions
return ORM models or plain rows/tuples; callers (services) own transaction
boundaries.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import ExternalIdentity

if TYPE_CHECKING:
    from app.models.external_identity import (
        IssueExternalIdentityMapping,
        SeriesMappingCommitReceipt,
        ThreadExternalSeriesMapping,
    )


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
            "comicpile_issue_id": issue_mapping.issue_id,
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
        "comicpile_issue_id": issue.id,
        "issue_number": issue.issue_number,
        "title": identity.metadata_json.get("name") if identity and identity.metadata_json else None,
        "thread_id": thread.id,
        "thread_title": thread.title,
        "current_mapping_status": mapping.status if mapping is not None else None,
        "provider": identity.provider if identity is not None else None,
        "external_id": identity.external_id if identity is not None else None,
        "confidence": mapping.confidence if mapping is not None else None,
    }


async def filter_owned_issue_ids(
    db: AsyncSession,
    *,
    user_id: int,
    issue_ids: list[int],
) -> set[int]:
    """Return the subset of issue IDs the user owns.

    Args:
        db: Database session.
        user_id: Owner user ID.
        issue_ids: Candidate ComicPile issue IDs.

    Returns:
        The subset of ``issue_ids`` belonging to a thread owned by ``user_id``.
    """
    from app.models.issue import Issue
    from app.models.thread import Thread

    if not issue_ids:
        return set()

    result = await db.execute(
        select(Issue.id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id.in_(issue_ids), Thread.user_id == user_id)
    )
    return set(result.scalars().all())


async def find_confirmed_identity_conflict(
    db: AsyncSession,
    *,
    issue_id: int,
    provider: str,
    external_identity_id: int,
) -> int | None:
    """Find a confirmed same-provider mapping that disagrees with the target identity.

    Args:
        db: Database session.
        issue_id: ComicPile issue ID.
        provider: Provider name.
        external_identity_id: External identity the bulk commit intends to confirm.

    Returns:
        The conflicting mapping row id, or ``None`` when the issue has no other
        confirmed mapping for ``provider``.
    """
    from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping

    result = await db.execute(
        select(IssueExternalIdentityMapping.id)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(
            IssueExternalIdentityMapping.issue_id == issue_id,
            IssueExternalIdentityMapping.status == "confirmed",
            IssueExternalIdentityMapping.external_identity_id != external_identity_id,
            ExternalIdentity.provider == provider,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def confirm_issue_mapping(
    db: AsyncSession,
    *,
    issue_id: int,
    external_identity_id: int,
    evidence_source: str,
    confidence: float,
) -> bool:
    """Confirm one issue-external identity mapping, converging on concurrent writers.

    The write is an ``ON CONFLICT DO NOTHING`` insert followed by an update, so two
    concurrent identical commits never create duplicate mappings. Returns ``True``
    when this call is the one that transitioned the mapping into ``confirmed``.

    Args:
        db: Database session owned by the calling service's transaction.
        issue_id: ComicPile issue ID.
        external_identity_id: External issue identity to confirm.
        evidence_source: Provenance recorded for the confirmation.
        confidence: Confidence recorded for the confirmation.

    Returns:
        True when this call performed the unresolved/candidate to confirmed transition.
    """
    from app.models.external_identity import IssueExternalIdentityMapping

    statement = (
        pg_insert(IssueExternalIdentityMapping)
        .values(
            issue_id=issue_id,
            external_identity_id=external_identity_id,
            status="confirmed",
            evidence_source=evidence_source,
            confidence=confidence,
        )
        .on_conflict_do_nothing(
            index_elements=[
                IssueExternalIdentityMapping.__table__.c.issue_id,
                IssueExternalIdentityMapping.__table__.c.external_identity_id,
            ]
        )
        .returning(IssueExternalIdentityMapping.id)
    )
    inserted_id = (await db.execute(statement)).scalar_one_or_none()
    if inserted_id is not None:
        return True

    mapping = (
        await db.execute(
            select(IssueExternalIdentityMapping).where(
                IssueExternalIdentityMapping.issue_id == issue_id,
                IssueExternalIdentityMapping.external_identity_id == external_identity_id,
            )
        )
    ).scalar_one()
    if mapping.status == "confirmed":
        return False
    mapping.status = "confirmed"
    mapping.evidence_source = evidence_source
    mapping.confidence = confidence
    await db.flush()
    return True


async def get_confirmed_issue_external_id(
    db: AsyncSession,
    *,
    issue_id: int,
    provider: str,
) -> str | None:
    """Return the provider external ID backing a confirmed issue mapping.

    Args:
        db: Database session.
        issue_id: ComicPile issue ID.
        provider: Provider name.

    Returns:
        The provider external ID of the confirmed mapping, or ``None``.
    """
    from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping

    return (
        await db.execute(
            select(ExternalIdentity.external_id)
            .join(
                IssueExternalIdentityMapping,
                IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
            )
            .where(
                IssueExternalIdentityMapping.issue_id == issue_id,
                IssueExternalIdentityMapping.status == "confirmed",
                ExternalIdentity.provider == provider,
            )
            .order_by(IssueExternalIdentityMapping.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_commit_receipt(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: str,
) -> SeriesMappingCommitReceipt | None:
    """Load a stored series-mapping commit receipt for one user and key.

    Args:
        db: Database session.
        user_id: Owner user ID.
        idempotency_key: Client-supplied idempotency key.

    Returns:
        The stored receipt, or ``None`` when the key has not been used.
    """
    from app.models.external_identity import SeriesMappingCommitReceipt

    return (
        await db.execute(
            select(SeriesMappingCommitReceipt).where(
                SeriesMappingCommitReceipt.user_id == user_id,
                SeriesMappingCommitReceipt.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()


async def reserve_commit_receipt(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: str,
    request_digest: str,
    provider: str,
    provider_series_external_id: str,
    origin_issue_id: int,
) -> bool:
    """Attempt to reserve an idempotency key inside the caller's transaction.

    PostgreSQL's speculative insertion waits for a concurrent inserter of the same
    key, so a lost race means the winning transaction has already committed and its
    receipt is readable. A losing caller must replay the stored response instead of
    repeating identity writes.

    Args:
        db: Database session owned by the calling service's transaction.
        user_id: Owner user ID.
        idempotency_key: Client-supplied idempotency key.
        request_digest: Digest of the complete material commit request.
        provider: Provider name bound to the token.
        provider_series_external_id: Provider series identity bound to the token.
        origin_issue_id: Anchor issue bound to the token.

    Returns:
        True when this call reserved the key, False when it is already taken.
    """
    from app.models.external_identity import SeriesMappingCommitReceipt

    statement = (
        pg_insert(SeriesMappingCommitReceipt)
        .values(
            user_id=user_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            provider=provider,
            provider_series_external_id=provider_series_external_id,
            origin_issue_id=origin_issue_id,
            response_json={},
        )
        .on_conflict_do_nothing(
            index_elements=[
                SeriesMappingCommitReceipt.__table__.c.user_id,
                SeriesMappingCommitReceipt.__table__.c.idempotency_key,
            ]
        )
        .returning(SeriesMappingCommitReceipt.id)
    )
    return (await db.execute(statement)).scalar_one_or_none() is not None


async def record_commit_receipt_response(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: str,
    response_json: dict[str, object],
) -> None:
    """Store the logical commit result on its reserved receipt.

    Args:
        db: Database session owned by the calling service's transaction.
        user_id: Owner user ID.
        idempotency_key: Client-supplied idempotency key.
        response_json: Serialized logical commit result.
    """
    from app.models.external_identity import SeriesMappingCommitReceipt

    receipt = (
        await db.execute(
            select(SeriesMappingCommitReceipt).where(
                SeriesMappingCommitReceipt.user_id == user_id,
                SeriesMappingCommitReceipt.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one()
    receipt.response_json = response_json
    await db.flush()

