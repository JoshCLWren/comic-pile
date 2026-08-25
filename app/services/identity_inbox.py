"""Service layer for the identity reconciliation inbox."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.external_identities import (
    ExternalIdentityMappingError,
    link_issue_external_identity,
)
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.identity_inbox import (
    IdentityInboxActionResponse,
    IdentityInboxCandidate,
    IdentityInboxItem,
    IdentityInboxSearchResponse,
    IdentityInboxSearchResult,
)
from comic_pile.comicvine_provider import ComicVineClient

logger = logging.getLogger(__name__)


def _dt_to_ts(dt: datetime | None) -> float | None:
    """Convert datetime to Unix timestamp."""
    return dt.timestamp() if dt is not None else None


def _source_entry_summary(
    thread_title: str, issue_number: str, metadata: dict[str, Any]
) -> str:
    """Build a human-readable summary of the source entry."""
    parts = [f"{thread_title} #{issue_number}"]
    volume = metadata.get("volume")
    if isinstance(volume, dict):
        vol_name = volume.get("name")
        if vol_name:
            parts.append(f"({vol_name})")
    publisher = metadata.get("publisher")
    if isinstance(publisher, str) and publisher:
        parts.append(f"- {publisher}")
    return " ".join(parts)


def _why_stopped(mapping: IssueExternalIdentityMapping) -> str:
    """Explain why the matcher stopped for this mapping."""
    evidence = mapping.evidence_json
    if not evidence:
        return "No candidates found"

    decision_reason = evidence.get("decision_reason", "")
    if decision_reason:
        return str(decision_reason)

    if mapping.status == "unresolved":
        return "No validated local candidate"

    if mapping.status == "candidate":
        return "Multiple candidates require explicit review"

    return f"Status: {mapping.status}"


async def list_inbox_items(
    db: AsyncSession,
    *,
    user_id: int,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[IdentityInboxItem], int]:
    """List unresolved or ambiguous external identity mappings for a user."""
    base_query = (
        select(IssueExternalIdentityMapping)
        .join(Issue, Issue.id == IssueExternalIdentityMapping.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(
            Thread.user_id == user_id,
            IssueExternalIdentityMapping.status.in_(["unresolved", "candidate", "deferred"]),
        )
    )

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        base_query.order_by(IssueExternalIdentityMapping.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    mappings = result.scalars().all()

    items = []
    for mapping in mappings:
        issue = await db.get(Issue, mapping.issue_id)
        thread = await db.get(Thread, issue.thread_id) if issue else None
        identity = await db.get(ExternalIdentity, mapping.external_identity_id)

        if not issue or not thread or not identity:
            continue

        issue_number = issue.issue_number or ""
        thread_title = thread.title or ""
        metadata = identity.metadata_json or {}

        items.append(
            IdentityInboxItem(
                mapping_id=mapping.id,
                issue_id=issue.id,
                thread_id=thread.id,
                thread_title=thread_title,
                issue_number=issue_number,
                status=mapping.status,
                provider=identity.provider,
                source_entry_summary=_source_entry_summary(
                    thread_title, issue_number, metadata
                ),
                why_stopped=_why_stopped(mapping),
                candidates=[],
                created_at=_dt_to_ts(mapping.created_at),
                updated_at=_dt_to_ts(mapping.updated_at),
            )
        )

    return items, total


async def get_inbox_item(
    db: AsyncSession,
    *,
    user_id: int,
    mapping_id: int,
) -> IdentityInboxItem | None:
    """Get a single inbox item with all its candidates."""
    mapping = await db.get(IssueExternalIdentityMapping, mapping_id)
    if mapping is None:
        return None

    issue = await db.get(Issue, mapping.issue_id)
    thread = await db.get(Thread, issue.thread_id) if issue else None

    if not thread or thread.user_id != user_id:
        return None

    identity = await db.get(ExternalIdentity, mapping.external_identity_id)
    if not identity or not issue:
        return None

    issue_number = issue.issue_number or ""
    thread_title = thread.title or ""
    metadata = identity.metadata_json or {}

    candidates_result = await db.execute(
        select(IssueExternalIdentityMapping)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(
            IssueExternalIdentityMapping.issue_id == issue.id,
            IssueExternalIdentityMapping.status.in_(
                ["candidate", "confirmed", "unresolved"]
            ),
        )
        .order_by(IssueExternalIdentityMapping.confidence.desc().nullslast())
    )
    candidate_mappings = candidates_result.scalars().all()

    candidates = []
    for cm in candidate_mappings:
        ext = await db.get(ExternalIdentity, cm.external_identity_id)
        if ext is None:
            continue
        candidates.append(
            IdentityInboxCandidate(
                external_identity_id=ext.id,
                provider=ext.provider,
                comicvine_id=ext.external_id,
                external_url=ext.external_url,
                metadata_json=ext.metadata_json or {},
                status=cm.status,
                confidence=cm.confidence,
                evidence_source=cm.evidence_source,
                evidence_json=cm.evidence_json or {},
                rejection_reason=cm.rejection_reason,
            )
        )

    return IdentityInboxItem(
        mapping_id=mapping.id,
        issue_id=issue.id,
        thread_id=thread.id,
        thread_title=thread_title,
        issue_number=issue_number,
        status=mapping.status,
        provider=identity.provider,
        source_entry_summary=_source_entry_summary(
            thread_title, issue_number, metadata
        ),
        why_stopped=_why_stopped(mapping),
        candidates=candidates,
        created_at=_dt_to_ts(mapping.created_at),
        updated_at=_dt_to_ts(mapping.updated_at),
    )


async def confirm_inbox_candidate(
    db: AsyncSession,
    *,
    user_id: int,
    mapping_id: int,
    external_identity_id: int,
) -> IdentityInboxActionResponse:
    """Confirm a candidate for an unresolved identity mapping."""
    mapping = await db.get(IssueExternalIdentityMapping, mapping_id)
    if mapping is None:
        raise ExternalIdentityMappingError("mapping not found")

    issue = await db.get(Issue, mapping.issue_id)
    thread = await db.get(Thread, issue.thread_id) if issue else None
    if not issue or not thread or thread.user_id != user_id:
        raise ExternalIdentityMappingError("mapping not owned by this user")

    await link_issue_external_identity(
        db,
        user_id=user_id,
        issue_id=issue.id,
        external_identity_id=external_identity_id,
        status="confirmed",
        evidence_source="user_confirmed",
        confidence=1.0,
    )

    identity = await db.get(ExternalIdentity, external_identity_id)
    if identity:
        other_mappings_result = await db.execute(
            select(IssueExternalIdentityMapping)
            .join(
                ExternalIdentity,
                ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
            )
            .where(
                IssueExternalIdentityMapping.issue_id == issue.id,
                IssueExternalIdentityMapping.external_identity_id != external_identity_id,
                IssueExternalIdentityMapping.status.in_(
                    ["candidate", "unresolved", "deferred"]
                ),
                ExternalIdentity.provider == identity.provider,
            )
        )
        other_mappings = other_mappings_result.scalars().all()
        for other in other_mappings:
            other.status = "rejected"
            other.rejection_reason = "replaced by user-confirmed candidate"

    await db.flush()

    updated_item = await get_inbox_item(db, user_id=user_id, mapping_id=mapping_id)

    return IdentityInboxActionResponse(
        success=True,
        message="Candidate confirmed successfully",
        updated_item=updated_item,
    )


async def reject_inbox_candidate(
    db: AsyncSession,
    *,
    user_id: int,
    mapping_id: int,
    external_identity_id: int,
    rejection_reason: str,
) -> IdentityInboxActionResponse:
    """Reject a candidate for an identity mapping."""
    mapping = await db.get(IssueExternalIdentityMapping, mapping_id)
    if mapping is None:
        raise ExternalIdentityMappingError("mapping not found")

    issue = await db.get(Issue, mapping.issue_id)
    thread = await db.get(Thread, issue.thread_id) if issue else None
    if not issue or not thread or thread.user_id != user_id:
        raise ExternalIdentityMappingError("mapping not owned by this user")

    await link_issue_external_identity(
        db,
        user_id=user_id,
        issue_id=issue.id,
        external_identity_id=external_identity_id,
        status="rejected",
        rejection_reason=rejection_reason,
    )
    await db.flush()

    updated_item = await get_inbox_item(db, user_id=user_id, mapping_id=mapping_id)

    return IdentityInboxActionResponse(
        success=True,
        message="Candidate rejected",
        updated_item=updated_item,
    )


async def defer_inbox_item(
    db: AsyncSession,
    *,
    user_id: int,
    mapping_id: int,
) -> IdentityInboxActionResponse:
    """Defer a mapping for later review."""
    mapping = await db.get(IssueExternalIdentityMapping, mapping_id)
    if mapping is None:
        raise ExternalIdentityMappingError("mapping not found")

    issue = await db.get(Issue, mapping.issue_id)
    thread = await db.get(Thread, issue.thread_id) if issue else None
    if not issue or not thread or thread.user_id != user_id:
        raise ExternalIdentityMappingError("mapping not owned by this user")

    mapping.status = "deferred"
    await db.flush()

    updated_item = await get_inbox_item(db, user_id=user_id, mapping_id=mapping_id)

    return IdentityInboxActionResponse(
        success=True,
        message="Item deferred for later review",
        updated_item=updated_item,
    )


async def skip_inbox_item(
    db: AsyncSession,
    *,
    user_id: int,
    mapping_id: int,
) -> IdentityInboxActionResponse:
    """Skip an inbox item for the current adoption workflow.

    This marks the mapping as rejected without a specific reason,
    indicating the user chose to skip this entry.
    """
    mapping = await db.get(IssueExternalIdentityMapping, mapping_id)
    if mapping is None:
        raise ExternalIdentityMappingError("mapping not found")

    issue = await db.get(Issue, mapping.issue_id)
    thread = await db.get(Thread, issue.thread_id) if issue else None
    if not issue or not thread or thread.user_id != user_id:
        raise ExternalIdentityMappingError("mapping not owned by this user")

    mapping.status = "rejected"
    mapping.rejection_reason = "skipped by user"
    await db.flush()

    updated_item = await get_inbox_item(db, user_id=user_id, mapping_id=mapping_id)

    return IdentityInboxActionResponse(
        success=True,
        message="Item skipped",
        updated_item=updated_item,
    )


def _coerce_provider_int(value: object) -> int | None:
    """Coerce a ComicVine value into an int when it is numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


async def search_comicvine_issues(
    client: ComicVineClient | None,
    *,
    query: str,
    limit: int = 10,
) -> IdentityInboxSearchResponse:
    """Search ComicVine for issues by query string.

    Args:
        client: Optional live ComicVine client. When ``None``, returns empty results.
        query: Search query string.
        limit: Maximum results to return (1-50).

    Returns:
        Issue search results with metadata.
    """
    if client is None or not query.strip():
        return IdentityInboxSearchResponse(
            issue_id=0, query=query, results=[], total_available=0
        )

    clamped_limit = max(1, min(limit, 50))
    response = await client.request(
        "search",
        "search",
        {
            "query": query,
            "resources": "issue",
            "limit": clamped_limit,
            "field_list": "id,name,issue_number,cover_date,volume,publisher,site_detail_url,image",
        },
    )
    results = response.payload.get("results")
    total = response.payload.get("number_of_total_results")
    if not isinstance(results, list):
        return IdentityInboxSearchResponse(
            issue_id=0, query=query, results=[], total_available=0
        )

    search_results: list[IdentityInboxSearchResult] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        issue_id = row.get("id")
        if not isinstance(issue_id, int):
            continue

        volume = row.get("volume")
        volume_id = None
        volume_name = None
        if isinstance(volume, dict):
            volume_id = volume.get("id") if isinstance(volume.get("id"), int) else None
            volume_name = volume.get("name") if isinstance(volume.get("name"), str) else None

        publisher_raw = row.get("publisher")
        publisher = None
        if isinstance(publisher_raw, dict):
            publisher = publisher_raw.get("name") if isinstance(publisher_raw.get("name"), str) else None
        elif isinstance(publisher_raw, str):
            publisher = publisher_raw

        image_raw = row.get("image")
        image_url = None
        if isinstance(image_raw, dict):
            image_url = image_raw.get("medium_url") or image_raw.get("small_url")

        cover_date = row.get("cover_date")
        start_year = None
        if isinstance(cover_date, str) and cover_date:
            # Extract year from cover_date (e.g., "2020-01-15")
            try:
                start_year = int(cover_date[:4])
            except (ValueError, IndexError):
                pass

        evidence: list[str] = []
        if volume_name:
            evidence.append(f"Volume: {volume_name}")
        if publisher:
            evidence.append(f"Publisher: {publisher}")

        search_results.append(
            IdentityInboxSearchResult(
                comicvine_issue_id=issue_id,
                comicvine_volume_id=volume_id,
                volume_name=volume_name,
                issue_number=str(row.get("issue_number")) if row.get("issue_number") is not None else None,
                issue_name=row.get("name") if isinstance(row.get("name"), str) else None,
                publisher=publisher,
                start_year=start_year,
                site_detail_url=row.get("site_detail_url") if isinstance(row.get("site_detail_url"), str) else None,
                image_url=image_url,
                score=None,  # ComicVine search doesn't return scores
                evidence=evidence,
            )
        )

    return IdentityInboxSearchResponse(
        issue_id=0,  # Will be set by caller
        query=query,
        results=search_results,
        total_available=total if isinstance(total, int) else len(search_results),
    )
