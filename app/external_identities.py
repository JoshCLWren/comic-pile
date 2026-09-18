"""Provider-independent external identity mapping services."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread

MAPPING_STATUSES = frozenset({"unresolved", "candidate", "confirmed", "rejected", "deferred"})
ENTITY_TYPES = frozenset({"issue", "series"})

_EXTERNAL_IDENTITY_BATCH_CHUNK_SIZE = 500
"""Max identities per batch statement.

The measured full CBL mirror carries ~85k distinct identities. Chunking keeps
bind parameters far below PostgreSQL's per-statement limit while still
reducing hundreds of thousands of sequential round trips to a few hundred.
"""


class ExternalIdentityMappingError(ValueError):
    """Raised when external identity evidence cannot be linked safely."""


@dataclass(frozen=True, slots=True)
class ExternalIdentitySpec:
    """Specification for an external identity to upsert."""

    provider: str
    entity_type: str
    external_id: str
    external_url: str | None = None
    metadata_json: dict[str, object] | None = None
    provider_updated_at: datetime | None = None


async def upsert_external_identities(
    db: AsyncSession,
    *,
    specs: Iterable[ExternalIdentitySpec],
) -> dict[tuple[str, str, str], ExternalIdentity]:
    """Create or update multiple provider identities in a single batch.

    Args:
        db: Async database session.
        specs: Iterable of identity specifications to upsert.

    Returns:
        Mapping from (provider, entity_type, external_id) to the created or existing
        external identity. Keys are normalized (lowercase provider/entity_type, trimmed
        external_id).

    Raises:
        ExternalIdentityMappingError: If any spec has empty provider/external_id or
            unsupported entity_type.
    """
    normalized_specs: list[ExternalIdentitySpec] = []
    for spec in specs:
        normalized_provider = spec.provider.strip().lower()
        normalized_entity_type = spec.entity_type.strip().lower()
        normalized_external_id = spec.external_id.strip()
        if not normalized_provider or not normalized_external_id:
            raise ExternalIdentityMappingError("provider and external_id are required")
        if normalized_entity_type not in ENTITY_TYPES:
            raise ExternalIdentityMappingError(f"unsupported entity_type: {spec.entity_type}")
        normalized_specs.append(
            ExternalIdentitySpec(
                provider=normalized_provider,
                entity_type=normalized_entity_type,
                external_id=normalized_external_id,
                external_url=spec.external_url,
                metadata_json=spec.metadata_json,
                provider_updated_at=spec.provider_updated_at,
            )
        )

    if not normalized_specs:
        return {}

    keys = [(s.provider, s.entity_type, s.external_id) for s in normalized_specs]
    unique_keys = list(dict.fromkeys(keys))

    existing_by_key: dict[tuple[str, str, str], ExternalIdentity] = {}
    for index in range(0, len(unique_keys), _EXTERNAL_IDENTITY_BATCH_CHUNK_SIZE):
        chunk = unique_keys[index : index + _EXTERNAL_IDENTITY_BATCH_CHUNK_SIZE]
        conditions = [
            (ExternalIdentity.provider == provider)
            & (ExternalIdentity.entity_type == entity_type)
            & (ExternalIdentity.external_id == external_id)
            for provider, entity_type, external_id in chunk
        ]
        combined_condition = conditions[0]
        for cond in conditions[1:]:
            combined_condition = combined_condition | cond
        rows = list(
            (await db.execute(select(ExternalIdentity).where(combined_condition))).scalars().all()
        )
        for row in rows:
            existing_by_key[(row.provider, row.entity_type, row.external_id)] = row

    seen_keys = set(existing_by_key.keys())
    unique_missing_specs: list[ExternalIdentitySpec] = []
    for spec in normalized_specs:
        key = (spec.provider, spec.entity_type, spec.external_id)
        if key not in seen_keys:
            seen_keys.add(key)
            unique_missing_specs.append(spec)

    if unique_missing_specs:
        for index in range(0, len(unique_missing_specs), _EXTERNAL_IDENTITY_BATCH_CHUNK_SIZE):
            chunk_specs = unique_missing_specs[index : index + _EXTERNAL_IDENTITY_BATCH_CHUNK_SIZE]
            statement = (
                pg_insert(ExternalIdentity)
                .values(
                    [
                        {
                            "provider": spec.provider,
                            "entity_type": spec.entity_type,
                            "external_id": spec.external_id,
                            "external_url": spec.external_url,
                            "metadata_json": spec.metadata_json or {},
                            "provider_updated_at": spec.provider_updated_at,
                        }
                        for spec in chunk_specs
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        ExternalIdentity.__table__.c.provider,
                        ExternalIdentity.__table__.c.entity_type,
                        ExternalIdentity.__table__.c.external_id,
                    ]
                )
            )
            try:
                async with db.begin_nested():
                    await db.execute(statement)
            except IntegrityError:
                # Roll back the savepoint only; the refresh below converges
                # to whatever the concurrent writer committed.
                pass

        refreshed_by_key: dict[tuple[str, str, str], ExternalIdentity] = {}
        for index in range(0, len(unique_keys), _EXTERNAL_IDENTITY_BATCH_CHUNK_SIZE):
            chunk = unique_keys[index : index + _EXTERNAL_IDENTITY_BATCH_CHUNK_SIZE]
            refresh_conditions = [
                (ExternalIdentity.provider == provider)
                & (ExternalIdentity.entity_type == entity_type)
                & (ExternalIdentity.external_id == external_id)
                for provider, entity_type, external_id in chunk
            ]
            combined_refresh = refresh_conditions[0]
            for cond in refresh_conditions[1:]:
                combined_refresh = combined_refresh | cond
            refreshed = list(
                (await db.execute(select(ExternalIdentity).where(combined_refresh)))
                .scalars()
                .all()
            )
            for row in refreshed:
                refreshed_by_key[(row.provider, row.entity_type, row.external_id)] = row
        existing_by_key = refreshed_by_key

    for spec in normalized_specs:
        key = (spec.provider, spec.entity_type, spec.external_id)
        identity = existing_by_key[key]
        if (
            spec.provider_updated_at is not None
            and identity.provider_updated_at is not None
            and spec.provider_updated_at < identity.provider_updated_at
        ):
            continue
        if spec.external_url is not None:
            identity.external_url = spec.external_url
        if spec.metadata_json is not None:
            identity.metadata_json = spec.metadata_json
        if spec.provider_updated_at is not None:
            identity.provider_updated_at = spec.provider_updated_at

    await db.flush()
    return {key: existing_by_key[key] for key in unique_keys}


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
        db: Async database session.
        provider: External provider name (normalized to lowercase).
        entity_type: Entity type, either "issue" or "series" (normalized to lowercase).
        external_id: Provider-specific identifier (whitespace trimmed).
        external_url: Optional URL to the external resource.
        metadata_json: Optional arbitrary metadata from the provider.
        provider_updated_at: Optional timestamp of last provider update; stale
            updates are ignored to prevent overwriting fresher data.

    Returns:
        The created or existing external identity.

    Raises:
        ExternalIdentityMappingError: If provider/external_id are empty or
            entity_type is unsupported.
    """
    normalized_provider = provider.strip().lower()
    normalized_entity_type = entity_type.strip().lower()
    normalized_external_id = external_id.strip()
    if not normalized_provider or not normalized_external_id:
        raise ExternalIdentityMappingError("provider and external_id are required")
    if normalized_entity_type not in ENTITY_TYPES:
        raise ExternalIdentityMappingError(f"unsupported entity_type: {entity_type}")

    identity_query = select(ExternalIdentity).where(
        ExternalIdentity.provider == normalized_provider,
        ExternalIdentity.entity_type == normalized_entity_type,
        ExternalIdentity.external_id == normalized_external_id,
    )
    identity = (await db.execute(identity_query)).scalar_one_or_none()
    if identity is None:
        try:
            async with db.begin_nested():
                identity = ExternalIdentity(
                    provider=normalized_provider,
                    entity_type=normalized_entity_type,
                    external_id=normalized_external_id,
                    external_url=external_url,
                    metadata_json=metadata_json or {},
                    provider_updated_at=provider_updated_at,
                )
                db.add(identity)
                await db.flush()
        except IntegrityError:
            identity = (await db.execute(identity_query)).scalar_one()
        else:
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
        db: Async database session.
        user_id: Owner user ID for authorization.
        issue_id: Issue to associate with the external identity.
        external_identity_id: External issue identity to link.
        status: Mapping status (unresolved, candidate, confirmed, rejected).
        evidence_source: Optional source of the evidence.
        confidence: Optional confidence score (0-1).
        rejection_reason: Optional reason when status is "rejected".

    Returns:
        The created or updated issue-external identity mapping.

    Raises:
        ExternalIdentityMappingError: If issue not owned, identity not an issue,
            provider conflict on confirm, or validation fails.
    """
    _validate_mapping_fields(status=status, confidence=confidence)
    owned_issue = await db.scalar(
        select(Issue.id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id == issue_id, Thread.user_id == user_id)
        .with_for_update(of=Issue)
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
        try:
            async with db.begin_nested():
                mapping = IssueExternalIdentityMapping(
                    issue_id=issue_id,
                    external_identity_id=external_identity_id,
                )
                db.add(mapping)
                await db.flush()
        except IntegrityError:
            result = await db.execute(
                select(IssueExternalIdentityMapping).where(
                    IssueExternalIdentityMapping.issue_id == issue_id,
                    IssueExternalIdentityMapping.external_identity_id == external_identity_id,
                )
            )
            mapping = result.scalar_one()

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

    Args:
        db: Async database session.
        user_id: Owner user ID for authorization.
        thread_id: Thread to associate with the series.
        external_identity_id: External series identity to link.
        status: Mapping status (unresolved, candidate, confirmed, rejected).
        evidence_source: Optional source of the evidence.
        confidence: Optional confidence score (0-1).

    Returns:
        The created or updated thread-series mapping.

    Raises:
        ExternalIdentityMappingError: If thread not owned, identity not a series,
            or validation fails.
    """
    _validate_mapping_fields(status=status, confidence=confidence)
    owned_thread = await db.scalar(
        select(Thread.id)
        .where(Thread.id == thread_id, Thread.user_id == user_id)
        .with_for_update(of=Thread)
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
        try:
            async with db.begin_nested():
                mapping = ThreadExternalSeriesMapping(
                    thread_id=thread_id,
                    external_identity_id=external_identity_id,
                )
                db.add(mapping)
                await db.flush()
        except IntegrityError:
            result = await db.execute(
                select(ThreadExternalSeriesMapping).where(
                    ThreadExternalSeriesMapping.thread_id == thread_id,
                    ThreadExternalSeriesMapping.external_identity_id == external_identity_id,
                )
            )
            mapping = result.scalar_one()

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
