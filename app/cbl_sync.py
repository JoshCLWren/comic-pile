"""Transactional persistence for parsed CBL mirror records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cbl_ingest import CBLBook, CBLList
from app.external_identities import (
    ExternalIdentitySpec,
    upsert_external_identities,
)
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList


@dataclass(frozen=True, slots=True)
class CBLSyncSummary:
    """Machine-readable outcome for one CBL mirror synchronization."""

    source_created: bool
    inserted_lists: int
    updated_lists: int
    deactivated_lists: int
    unchanged_lists: int
    entries_written: int
    identities_upserted: int
    dry_run: bool


class _IdentityCache:
    """In-run memoization cache for external identity upserts."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str], int] = {}
        self._pending_specs: dict[tuple[str, str, str], ExternalIdentitySpec] = {}
        self._upserted_count = 0

    def get(self, provider: str, entity_type: str, external_id: str) -> int | None:
        key = (provider.strip().lower(), entity_type.strip().lower(), external_id.strip())
        return self._cache.get(key)

    def add_pending(
        self,
        provider: str,
        entity_type: str,
        external_id: str,
        *,
        external_url: str | None = None,
        metadata_json: dict[str, object] | None = None,
        provider_updated_at: datetime | None = None,
    ) -> None:
        key = (provider.strip().lower(), entity_type.strip().lower(), external_id.strip())
        if key not in self._cache and key not in self._pending_specs:
            self._pending_specs[key] = ExternalIdentitySpec(
                provider=provider,
                entity_type=entity_type,
                external_id=external_id,
                external_url=external_url,
                metadata_json=metadata_json,
                provider_updated_at=provider_updated_at,
            )

    async def flush(self, db: AsyncSession) -> int:
        if not self._pending_specs:
            return 0
        specs = list(self._pending_specs.values())
        self._pending_specs.clear()
        results = await upsert_external_identities(db, specs=specs)
        for key, identity in results.items():
            self._cache[key] = identity.id
        self._upserted_count += len(results)
        return len(results)

    @property
    def upserted_count(self) -> int:
        return self._upserted_count


async def sync_cbl_lists(
    db: AsyncSession,
    *,
    repository: str,
    revision_sha: str,
    parsed_lists: tuple[CBLList, ...],
    protected_paths: frozenset[str] = frozenset(),
    dry_run: bool = False,
    synced_at: datetime | None = None,
) -> CBLSyncSummary:
    """Reconcile parsed CBL lists into normalized reference tables.

    The caller owns the surrounding transaction. Changed list entries are
    replaced inside that transaction, while files with an unchanged content
    hash are left untouched. Lists missing from the new mirror revision are
    retained and marked inactive rather than deleted. Paths that were present
    but failed parsing are protected from deactivation so malformed source data
    cannot erase the last known-good imported state.

    Args:
        db: Async database session participating in the sync transaction.
        repository: Stable source repository identity, for example
            ``JoshCLWren/CBL-ReadingLists``.
        revision_sha: Mirror revision being synchronized.
        parsed_lists: Successfully parsed CBL files for this revision.
        protected_paths: Source paths known to be present but unavailable for
            persistence, such as files that failed parsing.
        dry_run: Report intended changes without mutating persistence.
        synced_at: Optional deterministic synchronization timestamp for tests.

    Returns:
        Machine-readable counters describing the intended or applied changes.

    Raises:
        ValueError: If repository, revision, paths, or hashes are invalid.
    """
    normalized_repository = repository.strip()
    normalized_revision = revision_sha.strip()
    if not normalized_repository:
        raise ValueError("repository is required")
    if not normalized_revision:
        raise ValueError("revision_sha is required")

    paths = [item.source_path for item in parsed_lists]
    if any(not path.strip() for path in paths):
        raise ValueError("CBL source paths must be non-empty")
    if len(paths) != len(set(paths)):
        raise ValueError("CBL source paths must be unique within one sync")
    if any(not item.content_hash.strip() for item in parsed_lists):
        raise ValueError("CBL content hashes must be non-empty")
    if any(not path.strip() for path in protected_paths):
        raise ValueError("protected CBL source paths must be non-empty")

    source = await db.scalar(select(CBLSource).where(CBLSource.repository == normalized_repository))
    source_created = source is None

    existing_lists: list[CBLSourceList] = []
    if source is not None:
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
    existing_by_path = {item.source_path: item for item in existing_lists}
    incoming_paths = set(paths)

    inserted = 0
    updated = 0
    deactivated = 0
    unchanged = 0
    entries_written = 0

    for parsed in parsed_lists:
        existing = existing_by_path.get(parsed.source_path)
        if existing is None:
            inserted += 1
            entries_written += len(parsed.books)
            continue
        if existing.active and existing.content_hash == parsed.content_hash:
            unchanged += 1
            continue
        updated += 1
        entries_written += len(parsed.books)

    for existing in existing_lists:
        if (
            existing.active
            and existing.source_path not in incoming_paths
            and existing.source_path not in protected_paths
        ):
            deactivated += 1

    if dry_run:
        return CBLSyncSummary(
            source_created=source_created,
            inserted_lists=inserted,
            updated_lists=updated,
            deactivated_lists=deactivated,
            unchanged_lists=unchanged,
            entries_written=entries_written,
            identities_upserted=0,
            dry_run=True,
        )

    now = synced_at or datetime.now(UTC)
    if source is None:
        source = CBLSource(
            repository=normalized_repository,
            revision_sha=normalized_revision,
            synced_at=now,
        )
        db.add(source)
        await db.flush()
    else:
        source.revision_sha = normalized_revision
        source.synced_at = now

    identity_cache = _IdentityCache()

    # First pass: collect all identity specs from all books that will be written
    for parsed in parsed_lists:
        stored = existing_by_path.get(parsed.source_path)
        if stored is not None and stored.active and stored.content_hash == parsed.content_hash:
            continue
        for book in parsed.books:
            if book.comicvine_series_id is not None:
                identity_cache.add_pending("comicvine", "series", book.comicvine_series_id)
            if book.comicvine_issue_id is not None:
                identity_cache.add_pending("comicvine", "issue", book.comicvine_issue_id)

    # Flush identity cache to persist all unique identities
    await identity_cache.flush(db)

    # Second pass: create/update lists and entries with resolved identity IDs
    for parsed in parsed_lists:
        stored = existing_by_path.get(parsed.source_path)
        if stored is not None and stored.active and stored.content_hash == parsed.content_hash:
            continue

        if stored is None:
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
            stored.name = parsed.name
            stored.declared_issue_count = parsed.declared_issue_count
            stored.content_hash = parsed.content_hash
            stored.revision_sha = normalized_revision
            stored.active = True
            await db.execute(delete(CBLSourceEntry).where(CBLSourceEntry.list_id == stored.id))

        for book in parsed.books:
            db.add(_build_entry(stored.id, book, identity_cache))

    for stored in existing_lists:
        if (
            stored.active
            and stored.source_path not in incoming_paths
            and stored.source_path not in protected_paths
        ):
            stored.active = False
            stored.revision_sha = normalized_revision

    await db.flush()
    return CBLSyncSummary(
        source_created=source_created,
        inserted_lists=inserted,
        updated_lists=updated,
        deactivated_lists=deactivated,
        unchanged_lists=unchanged,
        entries_written=entries_written,
        identities_upserted=identity_cache.upserted_count,
        dry_run=False,
    )


def _build_entry(
    list_id: int,
    book: CBLBook,
    identity_cache: _IdentityCache,
) -> CBLSourceEntry:
    """Build one ordered entry with resolved ComicVine identity IDs."""
    series_identity_id = None
    issue_identity_id = None

    if book.comicvine_series_id is not None:
        series_identity_id = identity_cache.get("comicvine", "series", book.comicvine_series_id)

    if book.comicvine_issue_id is not None:
        issue_identity_id = identity_cache.get("comicvine", "issue", book.comicvine_issue_id)

    return CBLSourceEntry(
        list_id=list_id,
        position=book.position,
        series_name=book.series,
        issue_number=book.issue_number,
        volume_year=book.volume_year,
        publication_year=book.publication_year,
        external_series_identity_id=series_identity_id,
        external_issue_identity_id=issue_identity_id,
    )
