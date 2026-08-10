"""Provider-independent external identity mapping services."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread

MAPPING_STATUSES = frozenset({"unresolved", "candidate", "confirmed", "rejected"})
ENTITY_TYPES = frozenset({"issue", "series"})


class ExternalIdentityMappingError(ValueError):
    """Raised when external identity evidence cannot be linked safely."""


async def upsert_external_identity(
    db: AsyncSession,
    *,
    provider: str,
    entity_type: str,
    external_id: str,
    external_url: str | None = None,
    metadata_json: dict[str, object] | None = None,
    provider_updated_at: datetime | None = None,
) -> ExternalIdentity:
    """Create or update one provider identity without duplicating its stable key.

    Args:
        db: Active asynchronous database session.
        provider: Provider namespace, such as ``comicvine`` or ``cbl``.
        entity_type: ``issue`` or ``series``.
        external_id: Stable identifier inside the provider namespace.
        external_url: Optional diagnostic provider URL.
        metadata_json: Provider-specific identity metadata retained for diagnostics.
        provider_updated_at: Optional provider freshness timestamp.

    Returns:
        The existing or newly created external identity.

    Raises:
        ExternalIdentityMappingError: If required identity fields are invalid.
    """
    normalized_provider = provider.strip().lower()
    normalized_external_id = external_id.strip()
    if not normalized_provider or not normalized_external_id:
        raise ExternalIdentityMappingError("provider and external_id are required")
    if entity_type not in ENTITY_TYPES:
        raise ExternalIdentityMappingError(f"unsupported entity_type: {entity_type}")

    result = await db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == normalized_provider,
            ExternalIdentity.entity_type == entity_type,
            ExternalIdentity.external_id == normalized_external_id,
        )
    )
    identity = result.scalar_one_or_none()
    if identity is None:
        identity = ExternalIdentity(
            provider=normalized_provider,
            entity_type=entity_type,
            external_id=normalized_external_id,
            external_url=external_url,
            metadata_json=metadata_json or {},
            provider_updated_at=provider_updated_at,
        )
        db.add(identity)
        await db.flush()
        return identity

    if (
        provider_updated_at is not None
        and identity.provider_updated_at is not None
        and provider_updated_at < identity.provider_updated_at
    ):
        return identity

    if external_url is not None:
        identity.external_url = external_url
    if metadata_json is not None:
        identity.metadata_json = metadata_json
    if provider_updated_at is not None:
        identity.provider_updated_at = provider_updated_at
    await db.flush()
    return identity


async def link_issue_external_identity(
    db: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
    external_identity_id: int,
    status: str,
    evidence_source: str | None = None,
    confidence: float | None = None,
    rejection_reason: str | None = None,
) -> IssueExternalIdentityMapping:
    """Attach issue-level external evidence after enforcing user ownership.

    Args:
        db: Active asynchronous database session.
        user_id: Owner of the target ComicPile issue.
        issue_id: ComicPile issue to map.
        external_identity_id: Provider identity to attach.
        status: Mapping state.
        evidence_source: Human-readable provenance such as a CBL source path.
        confidence: Optional normalized score in the inclusive range 0..1.
        rejection_reason: Optional reason retained for rejected candidates.

    Returns:
        The idempotently created or updated mapping.

    Raises:
        ExternalIdentityMappingError: If ownership, entity type, status, or confidence is invalid.
    """
    _validate_mapping_fields(status=status, confidence=confidence)
    owned_issue = await db.scalar(
        select(Issue.id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id == issue_id, Thread.user_id == user_id)
    )
    if owned_issue is None:
        raise ExternalIdentityMappingError("issue is not owned by this user")

    identity = await db.get(ExternalIdentity, external_identity_id)
    if identity is None or identity.entity_type != "issue":
        raise ExternalIdentityMappingError("external identity is not an issue identity")

    if status == "confirmed":
        conflicting = await db.scalar(
            select(IssueExternalIdentityMapping.id)
            .join(
                ExternalIdentity,
                ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
            )
            .where(
                IssueExternalIdentityMapping.issue_id == issue_id,
                IssueExternalIdentityMapping.status == "confirmed",
                IssueExternalIdentityMapping.external_identity_id != external_identity_id,
                ExternalIdentity.provider == identity.provider,
            )
            .limit(1)
        )
        if conflicting is not None:
            raise ExternalIdentityMappingError(
                f"issue already has a confirmed {identity.provider} identity"
            )

    result = await db.execute(
        select(IssueExternalIdentityMapping).where(
            IssueExternalIdentityMapping.issue_id == issue_id,
            IssueExternalIdentityMapping.external_identity_id == external_identity_id,
        )
    )
    mapping = result.scalar_one_or_none()
    if mapping is None:
        mapping = IssueExternalIdentityMapping(
            issue_id=issue_id,
            external_identity_id=external_identity_id,
        )
        db.add(mapping)

    mapping.status = status
    mapping.evidence_source = evidence_source
    mapping.confidence = confidence
    mapping.rejection_reason = rejection_reason
    await db.flush()
    return mapping


async def link_thread_external_series(
    db: AsyncSession,
    *,
    user_id: int,
    thread_id: int,
    external_identity_id: int,
    status: str,
    evidence_source: str | None = None,
    confidence: float | None = None,
) -> ThreadExternalSeriesMapping:
    """Attach non-exclusive external series evidence to an owned reading thread.

    Multiple series identities may be confirmed for one thread because a ComicPile thread is a
    reading project rather than an external provider volume.
    """
    _validate_mapping_fields(status=status, confidence=confidence)
    owned_thread = await db.scalar(
        select(Thread.id).where(Thread.id == thread_id, Thread.user_id == user_id)
    )
    if owned_thread is None:
        raise ExternalIdentityMappingError("thread is not owned by this user")

    identity = await db.get(ExternalIdentity, external_identity_id)
    if identity is None or identity.entity_type != "series":
        raise ExternalIdentityMappingError("external identity is not a series identity")

    result = await db.execute(
        select(ThreadExternalSeriesMapping).where(
            ThreadExternalSeriesMapping.thread_id == thread_id,
            ThreadExternalSeriesMapping.external_identity_id == external_identity_id,
        )
    )
    mapping = result.scalar_one_or_none()
    if mapping is None:
        mapping = ThreadExternalSeriesMapping(
            thread_id=thread_id,
            external_identity_id=external_identity_id,
        )
        db.add(mapping)

    mapping.status = status
    mapping.evidence_source = evidence_source
    mapping.confidence = confidence
    await db.flush()
    return mapping


def _validate_mapping_fields(*, status: str, confidence: float | None) -> None:
    """Validate shared mapping state before touching persistence."""
    if status not in MAPPING_STATUSES:
        raise ExternalIdentityMappingError(f"unsupported mapping status: {status}")
    if confidence is not None and not 0 <= confidence <= 1:
        raise ExternalIdentityMappingError("confidence must be between 0 and 1")
