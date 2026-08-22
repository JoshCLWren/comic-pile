"""Catalog service layer for shared comic series and issue identities."""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.external_identities import (
    link_issue_external_identity,
    link_thread_external_series,
    upsert_external_identity,
)
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping, ThreadExternalSeriesMapping


MAPPING_STATUSES = frozenset({"unresolved", "candidate", "confirmed", "rejected"})


async def upsert_catalog_series(
    db: AsyncSession,
    *,
    provider: str,
    entity_type: str,
    external_id: str,
    external_url: str | None = None,
    metadata_json: dict[str, object] | None = None,
) -> ExternalIdentity:
    """Upsert a canonical series into the shared catalog (idempotent).

    If a canonical existing series can be identified, it is returned rather than
    silently duplicating a run.

    Args:
        db: Async database session.
        provider: External provider name (normalized to lowercase).
        entity_type: Entity type, either "issue" or "series" (normalized to lowercase).
        external_id: Provider-specific identifier (whitespace trimmed).
        external_url: Optional URL to the external resource.
        metadata_json: Optional arbitrary metadata from the provider.

    Returns:
        The created or existing external identity.
    """
    return await upsert_external_identity(
        db,
        provider=provider,
        entity_type=entity_type,
        external_id=external_id,
        external_url=external_url,
        metadata_json=metadata_json,
    )


async def upsert_catalog_issue(
    db: AsyncSession,
    *,
    provider: str,
    entity_type: str,
    external_id: str,
    external_url: str | None = None,
    metadata_json: dict[str, object] | None = None,
) -> ExternalIdentity:
    """Upsert a canonical issue into the shared catalog (idempotent).

    If a canonical existing issue can be identified, it is returned rather than
    silently duplicating a run.

    Args:
        db: Async database session.
        provider: External provider name (normalized to lowercase).
        entity_type: Entity type, either "issue" or "series" (normalized to lowercase).
        external_id: Provider-specific identifier (whitespace trimmed).
        external_url: Optional URL to the external resource.
        metadata_json: Optional arbitrary metadata from the provider.

    Returns:
        The created or existing external identity.
    """
    return await upsert_catalog_series(
        db,
        provider=provider,
        entity_type=entity_type,
        external_id=external_id,
        external_url=external_url,
        metadata_json=metadata_json,
    )


async def attach_series_to_thread(
    db: AsyncSession,
    *,
    user_id: int,
    thread_id: int,
    series_external_id: str,
    status: str,
    evidence_source: str | None = None,
    confidence: float | None = None,
) -> ThreadExternalSeriesMapping:
    """Attach a series identity to a user's reading thread.

    Args:
        db: Async database session.
        user_id: Owner user ID for authorization.
        thread_id: Thread to associate with the series.
        series_external_id: The external series identity external_id (e.g., ComicVine volume ID).
        status: Mapping status (unresolved, candidate, confirmed, rejected).
        evidence_source: Optional source of the evidence.
        confidence: Optional confidence score (0-1).

    Returns:
        The created or updated thread-series mapping.
    """
    _validate_mapping_status(status)

    # First, upsert the series identity if not already present
    identity = await upsert_catalog_series(
        db,
        provider="comicvine",
        entity_type="series",
        external_id=series_external_id,
    )

    mapping = await link_thread_external_series(
        db,
        user_id=user_id,
        thread_id=thread_id,
        external_identity_id=identity.id,
        status=status,
        evidence_source=evidence_source,
        confidence=confidence,
    )
    return mapping


async def attach_issue_to_thread(
    db: AsyncSession,
    *,
    user_id: int,
    thread_id: int,
    issue_id: int,
    provider: str,
    entity_type: str,
    external_id: str,
    external_url: str | None = None,
    metadata_json: dict[str, object] | None = None,
    status: str,
    evidence_source: str | None = None,
    confidence: float | None = None,
) -> IssueExternalIdentityMapping:
    """Attach an issue identity to a user's reading thread.

    Args:
        db: Async database session.
        user_id: Owner user ID for authorization.
        thread_id: Thread to associate with the issue.
        issue_id: Internal ComicPile issue ID to attach the external identity to.
        provider: External provider name.
        entity_type: Entity type ("issue" or "series").
        external_id: Provider-specific identifier.
        external_url: Optional URL to the external resource.
        metadata_json: Optional arbitrary metadata from the provider.
        status: Mapping status (unresolved, candidate, confirmed, rejected).
        evidence_source: Optional source of the evidence.
        confidence: Optional confidence score (0-1).

    Returns:
        The created or updated issue-external identity mapping.
    """
    _validate_mapping_status(status)

    # First, upsert the issue identity if not already present
    identity = await upsert_external_identity(
        db,
        provider=provider,
        entity_type=entity_type,
        external_id=external_id,
        external_url=external_url,
        metadata_json=metadata_json,
    )

    mapping = await link_issue_external_identity(
        db,
        user_id=user_id,
        issue_id=issue_id,
        external_identity_id=identity.id,
        status=status,
        evidence_source=evidence_source,
        confidence=confidence,
    )
    return mapping


def _validate_mapping_status(status: str) -> None:
    """Validate mapping status before persistence."""
    if status not in MAPPING_STATUSES:
        raise ValueError(f"unsupported mapping status: {status}")


async def reconcile_unmapped_issues(
    db: AsyncSession,
    *,
    provider: str = "comicvine",
    entity_type: str = "issue",
    status: str = "unresolved",
    limit: int | None = None,
) -> dict[str, int]:
    """Bounded backfill reconciliation for unmapped issues.

    Prioritizes: active `next_unread_issue_id` threads → other unread
    in threads with confirmed series → threads needing series resolution.
    Reports confirmed / candidate / unresolved / skipped counts.
    Idempotent on rerun: skips issues that already have a confirmed
    mapping; does not fabricate pseudo-identities.

    Args:
        db: Async database session.
        provider: External provider name.
        entity_type: Entity type ("issue" or "series").
        status: Target mapping status.
        limit: Maximum number of issues to process.

    Returns:
        Dict with counts: confirmed, candidate, unresolved, skipped.
    """
    from app.models.issue import Issue
    from app.models.thread import Thread

    counts = {"confirmed": 0, "candidate": 0, "unresolved": 0, "skipped": 0}

    # Prioritized query: next-unread gaps first, then unread with confirmed series,
    # then others. Avoid pseudo-identity fabrication.
    query = (
        select(Issue)
        .options(selectinload(Issue.thread))
        .join(Thread, Issue.thread_id == Thread.id)
        .outerjoin(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .where(
            Issue.status.in_(("unread", "reading")),
            IssueExternalIdentityMapping.external_identity_id.is_(None)
            | ~IssueExternalIdentityMapping.status.in_(("confirmed",)),
        )
        .order_by(
            # Active next_unread first
            func.coalesce(Thread.next_unread_issue_id == Issue.id, False).desc(),
            Issue.position,
        )
    )

    issues_result = await db.execute(query)
    issues = issues_result.scalars().unique().all()

    processed = 0
    for issue in issues:
        if limit is not None and processed >= limit:
            break

        # Skip if already confirmed (idempotent)
        existing = await db.execute(
            select(IssueExternalIdentityMapping)
            .where(
                IssueExternalIdentityMapping.issue_id == issue.id,
                IssueExternalIdentityMapping.status == "confirmed",
            )
            .limit(1)
        )
        if existing.scalars().first() is not None:
            counts["skipped"] += 1
            processed += 1
            continue

        # If the thread has a confirmed series identity, try a safe lookup
        # rather than fabricating a pseudo-identity.
        series_confirmed = await db.execute(
            select(ThreadExternalSeriesMapping)
            .join(
                ExternalIdentity,
                ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
            )
            .where(
                ThreadExternalSeriesMapping.thread_id == issue.thread_id,
                ThreadExternalSeriesMapping.status == "confirmed",
                ExternalIdentity.provider == provider,
                ExternalIdentity.entity_type == "series",
            )
            .limit(1)
        )
        series_mapping = series_confirmed.scalars().first()

        if series_mapping is not None:
            # Create a safe candidate mapping without pseudo-identity fabrication.
            # We use the confirmed series identity's external series id as reference,
            # and set status to candidate (not confirmed) to avoid false auto-confirm.
            await link_issue_external_identity(
                db,
                user_id=issue.thread.user_id,
                issue_id=issue.id,
                external_identity_id=series_mapping.external_identity_id,
                status="candidate",
                confidence=0.5,
                evidence_source="bounded_backfill_series_ref",
            )
            counts["candidate"] += 1
        else:
            # No confirmed series; mark unresolved without fabricating identity.
            # We do not create a pseudo-identity here; instead we rely on manual
            # series resolution or future backfill.
            counts["unresolved"] += 1

        processed += 1

    return counts
