"""Service layer for the identity reconciliation inbox."""

from __future__ import annotations

import logging

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
)

logger = logging.getLogger(__name__)


def _dt_to_ts(dt):  # noqa: ANN001
    """Convert datetime to Unix timestamp."""
    return dt.timestamp() if dt is not None else None


def _source_entry_summary(thread_title, issue_number, metadata):  # noqa: ANN001
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


def _why_stopped(mapping):  # noqa: ANN001
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


async def list_inbox_items(  # noqa: ANN201
    db,
    *,
    user_id,
    offset=0,
    limit=50,
):
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


async def get_inbox_item(  # noqa: ANN201
    db,
    *,
    user_id,
    mapping_id,
):
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


async def confirm_inbox_candidate(  # noqa: ANN201
    db,
    *,
    user_id,
    mapping_id,
    external_identity_id,
):
    """Confirm a candidate for an unresolved identity mapping."""
    mapping = await db.get(IssueExternalIdentityMapping, mapping_id)
    if mapping is None:
        raise ExternalIdentityMappingError("mapping not found")

    issue = await db.get(Issue, mapping.issue_id)
    thread = await db.get(Thread, issue.thread_id) if issue else None
    if not thread or thread.user_id != user_id:
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


async def reject_inbox_candidate(  # noqa: ANN201
    db,
    *,
    user_id,
    mapping_id,
    external_identity_id,
    rejection_reason,
):
    """Reject a candidate for an identity mapping."""
    mapping = await db.get(IssueExternalIdentityMapping, mapping_id)
    if mapping is None:
        raise ExternalIdentityMappingError("mapping not found")

    issue = await db.get(Issue, mapping.issue_id)
    thread = await db.get(Thread, issue.thread_id) if issue else None
    if not thread or thread.user_id != user_id:
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


async def defer_inbox_item(  # noqa: ANN201
    db,
    *,
    user_id,
    mapping_id,
):
    """Defer a mapping for later review."""
    mapping = await db.get(IssueExternalIdentityMapping, mapping_id)
    if mapping is None:
        raise ExternalIdentityMappingError("mapping not found")

    issue = await db.get(Issue, mapping.issue_id)
    thread = await db.get(Thread, issue.thread_id) if issue else None
    if not thread or thread.user_id != user_id:
        raise ExternalIdentityMappingError("mapping not owned by this user")

    mapping.status = "deferred"
    await db.flush()

    updated_item = await get_inbox_item(db, user_id=user_id, mapping_id=mapping_id)

    return IdentityInboxActionResponse(
        success=True,
        message="Item deferred for later review",
        updated_item=updated_item,
    )


async def skip_inbox_item(  # noqa: ANN201
    db,
    *,
    user_id,
    mapping_id,
):
    """Skip an inbox item for the current adoption workflow.

    This marks the mapping as rejected without a specific reason,
    indicating the user chose to skip this entry.
    """
    mapping = await db.get(IssueExternalIdentityMapping, mapping_id)
    if mapping is None:
        raise ExternalIdentityMappingError("mapping not found")

    issue = await db.get(Issue, mapping.issue_id)
    thread = await db.get(Thread, issue.thread_id) if issue else None
    if not thread or thread.user_id != user_id:
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
