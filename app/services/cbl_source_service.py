"""Read-only CBL source list discovery and detail previews.

These helpers read persisted CBL provenance only. They never adopt, reconcile,
repair, or otherwise mutate reader-owned issues, threads, or identity mappings.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.cbl_source_repository import (
    discover_cbl_source_lists as discover_source_rows,
    get_cbl_source_list_detail as load_source_list_detail,
)
from app.services.cbl_source_public import (
    public_cbl_repository,
    public_cbl_source_path,
    public_cbl_source_ref,
)


@dataclass(frozen=True)
class CBLSourceListSummary:
    """One active persisted source list available for preview."""

    id: int
    name: str
    source_path: str
    source_repository: str
    declared_issue_count: int | None
    content_hash: str
    revision_sha: str


@dataclass(frozen=True)
class CBLSourceEntryPreview:
    """One ordered source occurrence in a CBL list."""

    position: int
    series_name: str
    issue_number: str
    volume_year: int | None
    publication_year: int | None
    comicvine_issue_id: str | None
    comicvine_volume_id: str | None


@dataclass(frozen=True)
class CBLSourceListPreview:
    """Read-only preview of one CBL source list and one page of its entries."""

    id: int
    name: str
    source_path: str
    source_repository: str
    source_ref: str
    declared_issue_count: int | None
    content_hash: str
    revision_sha: str
    entries_total: int
    entries_offset: int
    entries_limit: int
    entries: tuple[CBLSourceEntryPreview, ...]


async def list_cbl_source_previews(
    db: AsyncSession,
    *,
    query_text: str | None,
    limit: int,
) -> list[CBLSourceListSummary]:
    """Return active CBL source lists available for preview.

    Args:
        db: Database session.
        query_text: Optional case-insensitive match against list name or source path.
        limit: Maximum number of lists to return.

    Returns:
        Reader-safe summaries of the matching active source lists.
    """
    rows = await discover_source_rows(db, query_text=query_text, limit=limit)
    return [
        CBLSourceListSummary(
            id=source_list.id,
            name=source_list.name,
            source_path=source_list.source_path,
            source_repository=public_cbl_repository(repository),
            declared_issue_count=source_list.declared_issue_count,
            content_hash=source_list.content_hash,
            revision_sha=source_list.revision_sha,
        )
        for source_list, repository in rows
    ]


async def get_cbl_source_list_preview(
    db: AsyncSession,
    *,
    list_id: int,
    offset: int,
    limit: int,
) -> CBLSourceListPreview | None:
    """Return one active CBL source list with a bounded page of ordered entries.

    Args:
        db: Database session.
        list_id: CBL source list identifier.
        offset: Zero-based index of the first returned source occurrence.
        limit: Maximum number of source occurrences to return.

    Returns:
        The reader-safe source list preview, or ``None`` when the list is
        missing or inactive.
    """
    detail = await load_source_list_detail(db, list_id=list_id, offset=offset, limit=limit)
    if detail is None:
        return None
    source_list, repository, entries_total, entries = detail
    return CBLSourceListPreview(
        id=source_list.id,
        name=source_list.name,
        source_path=public_cbl_source_path(source_list.source_path),
        source_repository=public_cbl_repository(repository),
        source_ref=public_cbl_source_ref(repository, source_list.source_path),
        declared_issue_count=source_list.declared_issue_count,
        content_hash=source_list.content_hash,
        revision_sha=source_list.revision_sha,
        entries_total=entries_total,
        entries_offset=offset,
        entries_limit=limit,
        entries=tuple(
            CBLSourceEntryPreview(
                position=entry.position,
                series_name=entry.series_name,
                issue_number=entry.issue_number,
                volume_year=entry.volume_year,
                publication_year=entry.publication_year,
                comicvine_issue_id=comicvine_issue_id,
                comicvine_volume_id=comicvine_volume_id,
            )
            for entry, comicvine_issue_id, comicvine_volume_id in entries
        ),
    )
