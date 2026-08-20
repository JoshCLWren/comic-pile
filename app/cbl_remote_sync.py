"""Incremental persistence helpers for service-authorized CBL synchronization."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cbl_ingest import CBLList
from app.cbl_sync import CBLSyncSummary, _build_entry
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList


async def get_cbl_source_revision(db: AsyncSession, *, repository: str) -> str | None:
    """Return the last fully synchronized source revision.

    Args:
        db: Application database session.
        repository: Stable source repository identity.

    Returns:
        The stored revision marker, or ``None`` when the source has never synchronized.

    Raises:
        ValueError: If the repository identity is blank.
    """
    normalized_repository = repository.strip()
    if not normalized_repository:
        raise ValueError("repository is required")
    return await db.scalar(
        select(CBLSource.revision_sha).where(CBLSource.repository == normalized_repository)
    )


async def _get_or_create_locked_source(
    db: AsyncSession,
    *,
    repository: str,
    pending_revision: str,
    synced_at: datetime,
) -> tuple[CBLSource, bool]:
    """Get one locked source row or create it safely under concurrent requests.

    Args:
        db: Application database session.
        repository: Normalized source repository identity.
        pending_revision: Pending revision marker stored for a new source.
        synced_at: Synchronization timestamp for a newly created source.

    Returns:
        The locked source row and whether this call created it.

    Raises:
        RuntimeError: If a concurrent insert wins but the row cannot be reloaded.
    """
    source = await db.scalar(
        select(CBLSource).where(CBLSource.repository == repository).with_for_update()
    )
    if source is not None:
        return source, False

    candidate = CBLSource(
        repository=repository,
        revision_sha=pending_revision,
        synced_at=synced_at,
    )
    try:
        async with db.begin_nested():
            db.add(candidate)
            await db.flush()
    except IntegrityError:
        source = await db.scalar(
            select(CBLSource).where(CBLSource.repository == repository).with_for_update()
        )
        if source is None:
            raise RuntimeError("concurrent CBL source creation could not be reconciled")
        return source, False
    return candidate, True


async def sync_cbl_batch(
    db: AsyncSession,
    *,
    repository: str,
    revision_sha: str,
    parsed_lists: tuple[CBLList, ...],
    synced_at: datetime | None = None,
) -> CBLSyncSummary:
    """Upsert a bounded batch without publishing the source revision as complete.

    Args:
        db: Application database session.
        repository: Stable source repository identity.
        revision_sha: Source revision represented by this batch.
        parsed_lists: Parsed CBL lists included in this bounded batch.
        synced_at: Optional deterministic timestamp for tests.

    Returns:
        Machine-readable counters describing the persisted batch.

    Raises:
        ValueError: If source metadata or parsed list metadata is invalid.
        RuntimeError: If concurrent source creation cannot be reconciled.
    """
    normalized_repository = repository.strip()
    normalized_revision = revision_sha.strip()
    if not normalized_repository:
        raise ValueError("repository is required")
    if not normalized_revision:
        raise ValueError("revision_sha is required")
    if not parsed_lists:
        raise ValueError("parsed_lists must not be empty")

    paths = [item.source_path for item in parsed_lists]
    if any(not path.strip() for path in paths):
        raise ValueError("CBL source paths must be non-empty")
    if len(paths) != len(set(paths)):
        raise ValueError("CBL source paths must be unique within one batch")
    if any(not item.content_hash.strip() for item in parsed_lists):
        raise ValueError("CBL content hashes must be non-empty")

    pending_marker = f"pending:{normalized_revision}"
    source, source_created = await _get_or_create_locked_source(
        db,
        repository=normalized_repository,
        pending_revision=pending_marker,
        synced_at=synced_at or datetime.now(UTC),
    )
    source.revision_sha = pending_marker

    existing_lists = list(
        (
            await db.execute(
                select(CBLSourceList)
                .where(
                    CBLSourceList.source_id == source.id,
                    CBLSourceList.source_path.in_(paths),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    existing_by_path = {item.source_path: item for item in existing_lists}

    inserted = 0
    updated = 0
    unchanged = 0
    entries_written = 0

    for parsed in parsed_lists:
        stored = existing_by_path.get(parsed.source_path)
        if stored is not None and stored.active and stored.content_hash == parsed.content_hash:
            unchanged += 1
            continue

        if stored is None:
            inserted += 1
            stored = CBLSourceList(
                source_id=source.id,
                source_path=parsed.source_path,
                name=parsed.name,
                declared_issue_count=parsed.declared_issue_count,
                content_hash=parsed.content_hash,
                revision_sha=normalized_revision,
                active=True,
            )
            db.add(stored)
            await db.flush()
        else:
            updated += 1
            stored.name = parsed.name
            stored.declared_issue_count = parsed.declared_issue_count
            stored.content_hash = parsed.content_hash
            stored.revision_sha = normalized_revision
            stored.active = True
            await db.execute(delete(CBLSourceEntry).where(CBLSourceEntry.list_id == stored.id))

        for book in parsed.books:
            db.add(await _build_entry(db, list_id=stored.id, book=book))
            entries_written += 1

    await db.flush()
    return CBLSyncSummary(
        source_created=source_created,
        inserted_lists=inserted,
        updated_lists=updated,
        deactivated_lists=0,
        unchanged_lists=unchanged,
        entries_written=entries_written,
        dry_run=False,
    )


async def finalize_cbl_sync(
    db: AsyncSession,
    *,
    repository: str,
    revision_sha: str,
    active_paths: frozenset[str],
    protected_paths: frozenset[str] = frozenset(),
    synced_at: datetime | None = None,
) -> CBLSyncSummary:
    """Deactivate removed lists and publish a revision after every batch succeeds.

    Args:
        db: Application database session.
        repository: Stable source repository identity.
        revision_sha: Source revision to publish as fully synchronized.
        active_paths: Complete set of successfully parsed list paths.
        protected_paths: Present paths whose prior known-good state must be preserved.
        synced_at: Optional deterministic timestamp for tests.

    Returns:
        Machine-readable counters describing finalization and deactivation work.

    Raises:
        ValueError: If metadata is invalid, the source is missing, or the pending
            revision does not match the revision being finalized.
    """
    normalized_repository = repository.strip()
    normalized_revision = revision_sha.strip()
    if not normalized_repository:
        raise ValueError("repository is required")
    if not normalized_revision:
        raise ValueError("revision_sha is required")
    if any(not path.strip() for path in active_paths | protected_paths):
        raise ValueError("CBL source paths must be non-empty")

    source = await db.scalar(
        select(CBLSource).where(CBLSource.repository == normalized_repository).with_for_update()
    )
    if source is None:
        raise ValueError("CBL source must exist before finalization")
    expected_pending = f"pending:{normalized_revision}"
    if source.revision_sha != expected_pending:
        raise ValueError("no matching pending CBL revision exists for finalization")

    existing_lists = list(
        (
            await db.execute(
                select(CBLSourceList)
                .where(CBLSourceList.source_id == source.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    deactivated = 0
    for stored in existing_lists:
        if (
            stored.active
            and stored.source_path not in active_paths
            and stored.source_path not in protected_paths
        ):
            stored.active = False
            stored.revision_sha = normalized_revision
            deactivated += 1

    source.revision_sha = normalized_revision
    source.synced_at = synced_at or datetime.now(UTC)
    await db.flush()
    return CBLSyncSummary(
        source_created=False,
        inserted_lists=0,
        updated_lists=0,
        deactivated_lists=deactivated,
        unchanged_lists=0,
        entries_written=0,
        dry_run=False,
    )
