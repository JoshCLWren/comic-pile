"""Read-only reverse lookup of CBL sources by exact Comic Vine issue identity.

This service answers one question: which shared CBL source lists contain a
given exact Comic Vine issue identity, and at which source positions?

The answer never depends on the caller. It never reads reader-owned Issues,
identity mappings, read state, or adoption state, and it never writes to any
table.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.cbl_comicvine_lookup_repository import (
    find_cbl_source_occurrences_by_comicvine_issue as find_occurrence_rows,
)
from app.services.cbl_source_public import (
    public_cbl_repository,
    public_cbl_source_path,
    public_cbl_source_ref,
)


@dataclass(frozen=True, slots=True)
class CBLComicvineOccurrence:
    """One source occurrence of an exact Comic Vine issue identity."""

    list_id: int
    list_name: str
    source_path: str
    source_repository: str
    source_ref: str
    revision_sha: str
    position: int
    series_name: str
    issue_number: str
    volume_year: int | None
    publication_year: int | None
    comicvine_issue_id: str
    comicvine_volume_id: str | None


@dataclass(frozen=True, slots=True)
class CBLComicvineOccurrencePage:
    """One page of source occurrences plus the whole-match totals."""

    comicvine_issue_id: str
    occurrences_total: int
    lists_total: int
    occurrences_offset: int
    occurrences_limit: int
    occurrences: tuple[CBLComicvineOccurrence, ...]


async def search_cbl_sources_by_comicvine_issue(
    db: AsyncSession,
    *,
    comicvine_issue_id: str,
    offset: int,
    limit: int,
) -> CBLComicvineOccurrencePage:
    """Return the shared CBL source lists containing one exact Comic Vine issue.

    The lookup is exact on the Comic Vine issue identity, so it returns every
    source list and source position that holds the identity, including
    repeated occurrences inside one list and the same identity in several
    lists. The series/volume identity of each occurrence is reported as
    context so a reader can tell same-titled volumes apart.

    Args:
        db: Database session.
        comicvine_issue_id: Exact Comic Vine issue external ID.
        offset: Zero-based index of the first returned source occurrence.
        limit: Maximum number of source occurrences to return.

    Returns:
        The matching source occurrences with the total occurrence count and
        the number of distinct source lists that contain the identity.
    """
    normalized_issue_id = comicvine_issue_id.strip()
    rows = await find_occurrence_rows(
        db,
        comicvine_issue_id=normalized_issue_id,
        offset=offset,
        limit=limit,
    )

    return CBLComicvineOccurrencePage(
        comicvine_issue_id=normalized_issue_id,
        occurrences_total=rows.occurrences_total,
        lists_total=rows.lists_total,
        occurrences_offset=offset,
        occurrences_limit=limit,
        occurrences=tuple(
            CBLComicvineOccurrence(
                list_id=row.source_list.id,
                list_name=row.source_list.name,
                source_path=public_cbl_source_path(row.source_list.source_path),
                source_repository=public_cbl_repository(row.source.repository),
                source_ref=public_cbl_source_ref(
                    row.source.repository, row.source_list.source_path
                ),
                revision_sha=row.source_list.revision_sha,
                position=row.entry.position,
                series_name=row.entry.series_name,
                issue_number=row.entry.issue_number,
                volume_year=row.entry.volume_year,
                publication_year=row.entry.publication_year,
                comicvine_issue_id=normalized_issue_id,
                comicvine_volume_id=row.comicvine_volume_id,
            )
            for row in rows.occurrences
        ),
    )
