"""Read-only reverse lookup of CBL source occurrences by Comic Vine issue identity.

The shared CBL catalog is reader-independent. These queries therefore never
join ``issues`` or ``issue_external_identity_mappings``: an exact Comic Vine
issue identity finds every source list and source position that contains it,
whether or not any reader owns a matching Issue.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, and_, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import ExternalIdentity

COMICVINE_PROVIDER = "comicvine"
ISSUE_ENTITY_TYPE = "issue"
SERIES_ENTITY_TYPE = "series"


@dataclass(frozen=True, slots=True)
class CBLComicvineOccurrenceRow:
    """One persisted source occurrence of an exact Comic Vine issue identity."""

    entry: CBLSourceEntry
    source_list: CBLSourceList
    source: CBLSource
    comicvine_volume_id: str | None


@dataclass(frozen=True, slots=True)
class CBLComicvineOccurrenceRows:
    """One page of occurrences plus the whole-match totals."""

    occurrences_total: int
    lists_total: int
    occurrences: tuple[CBLComicvineOccurrenceRow, ...]


@dataclass(frozen=True, slots=True)
class CBLSourceCoverageRow:
    """One shared source list that contains at least one compared input comic."""

    source_list: CBLSourceList
    source: CBLSource
    entries_total: int
    distinct_source_issues: int


@dataclass(frozen=True, slots=True)
class CBLMatchedSourceEntryRow:
    """One source occurrence whose exact Comic Vine issue ID matches an input ID."""

    list_id: int
    position: int
    comicvine_issue_id: str
    series_name: str
    issue_number: str
    volume_year: int | None
    publication_year: int | None
    comicvine_volume_id: str | None


def _matching_issue_identity_ids(comicvine_issue_id: str) -> Select[int]:
    """Return the Comic Vine issue identity rows for one exact external ID.

    Args:
        comicvine_issue_id: Exact Comic Vine issue external ID.

    Returns:
        A select of matching ``external_identities.id`` values. The provider,
        entity type, and external ID together are unique, so at most one row
        can match.
    """
    return (
        select(ExternalIdentity.id)
        .where(
            ExternalIdentity.provider == COMICVINE_PROVIDER,
            ExternalIdentity.entity_type == ISSUE_ENTITY_TYPE,
            ExternalIdentity.external_id == comicvine_issue_id,
        )
    )


def _matching_entries(
    comicvine_issue_id: str,
) -> Select[CBLSourceEntry, CBLSourceList, CBLSource, str]:
    """Return the base select for source entries holding one exact identity.

    Only active source lists participate: an inactive list was removed from
    the current mirror revision and is no longer part of the shared catalog.

    Args:
        comicvine_issue_id: Exact Comic Vine issue external ID.

    Returns:
        A select of matching entries with their list, source, and the Comic
        Vine volume identity that gives the occurrence its series context.
    """
    volume_identity = aliased(ExternalIdentity)
    return (
        select(
            CBLSourceEntry,
            CBLSourceList,
            CBLSource,
            volume_identity.external_id.label("comicvine_volume_id"),
        )
        .join(CBLSourceList, CBLSourceList.id == CBLSourceEntry.list_id)
        .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
        .outerjoin(
            volume_identity,
            and_(
                volume_identity.id == CBLSourceEntry.external_series_identity_id,
                volume_identity.provider == COMICVINE_PROVIDER,
                volume_identity.entity_type == SERIES_ENTITY_TYPE,
            ),
        )
        .where(
            CBLSourceList.active.is_(True),
            CBLSourceEntry.external_issue_identity_id.in_(
                _matching_issue_identity_ids(comicvine_issue_id)
            ),
        )
    )


def _matching_entry_count_statement(
    comicvine_issue_id: str,
    *,
    distinct_lists: bool,
) -> Select[int]:
    """Return the count statement for one exact Comic Vine issue identity.

    Args:
        comicvine_issue_id: Exact Comic Vine issue external ID.
        distinct_lists: Count distinct source lists instead of source
            occurrences.

    Returns:
        A count select over the active source entries holding the identity.
    """
    counted = distinct(CBLSourceList.id) if distinct_lists else CBLSourceEntry.id
    return (
        select(func.count(counted))
        .select_from(CBLSourceEntry)
        .join(CBLSourceList, CBLSourceList.id == CBLSourceEntry.list_id)
        .where(
            CBLSourceList.active.is_(True),
            CBLSourceEntry.external_issue_identity_id.in_(
                _matching_issue_identity_ids(comicvine_issue_id)
            ),
        )
    )


async def find_cbl_source_occurrences_by_comicvine_issue(
    db: AsyncSession,
    *,
    comicvine_issue_id: str,
    offset: int,
    limit: int,
) -> CBLComicvineOccurrenceRows:
    """Return every source occurrence of one exact Comic Vine issue identity.

    The match is exact on the provider identity, so a shared series title, a
    shared volume, or a same-numbered issue in another volume never produces a
    false positive. Repeated occurrences inside one source list stay separate
    rows with their own source positions.

    Args:
        db: Database session.
        comicvine_issue_id: Exact Comic Vine issue external ID.
        offset: Zero-based index of the first returned source occurrence.
        limit: Maximum number of source occurrences to return.

    Returns:
        The matching source occurrences in stable list-then-position order,
        the total number of matching occurrences, and the number of distinct
        source lists that contain the identity.
    """
    entries_statement = _matching_entries(comicvine_issue_id)

    occurrences_total = int(
        await db.scalar(
            _matching_entry_count_statement(comicvine_issue_id, distinct_lists=False)
        )
        or 0
    )

    lists_total = int(
        await db.scalar(
            _matching_entry_count_statement(comicvine_issue_id, distinct_lists=True)
        )
        or 0
    )

    page_statement = (
        entries_statement.order_by(
            CBLSourceList.name.asc(),
            CBLSourceList.source_path.asc(),
            CBLSourceList.id.asc(),
            CBLSourceEntry.position.asc(),
            CBLSourceEntry.id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(page_statement)).all()

    return CBLComicvineOccurrenceRows(
        occurrences_total=occurrences_total,
        lists_total=lists_total,
        occurrences=tuple(
            CBLComicvineOccurrenceRow(
                entry=row[0],
                source_list=row[1],
                source=row[2],
                comicvine_volume_id=row[3],
            )
            for row in rows
        ),
    )


async def find_cbl_source_coverage_candidates(
    db: AsyncSession,
    *,
    comicvine_issue_ids: tuple[str, ...],
) -> tuple[CBLSourceCoverageRow, ...]:
    """Return shared source lists that contain at least one exact input identity.

    Candidate discovery is limited to active source lists. A list qualifies
    only when one of its entries joins a Comic Vine issue identity whose exact
    external ID is in ``comicvine_issue_ids``. Same-titled volumes, same issue
    numbers, and reader-owned Issue rows never create a candidate.

    Args:
        db: Database session.
        comicvine_issue_ids: Distinct exact Comic Vine issue external IDs.

    Returns:
        One aggregate row per candidate source list with its total entry count
        and its distinct confirmed Comic Vine issue count.
    """
    if not comicvine_issue_ids:
        return ()

    issue_identity = aliased(ExternalIdentity)
    matching_list_ids = (
        select(CBLSourceEntry.list_id.label("list_id"))
        .join(
            issue_identity,
            and_(
                issue_identity.id == CBLSourceEntry.external_issue_identity_id,
                issue_identity.provider == COMICVINE_PROVIDER,
                issue_identity.entity_type == ISSUE_ENTITY_TYPE,
            ),
        )
        .where(issue_identity.external_id.in_(comicvine_issue_ids))
        .distinct()
        .subquery()
    )

    statement = (
        select(
            CBLSourceList,
            CBLSource,
            func.count(CBLSourceEntry.id).label("entries_total"),
            func.count(func.distinct(issue_identity.id)).label("distinct_source_issues"),
        )
        .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
        .join(CBLSourceEntry, CBLSourceEntry.list_id == CBLSourceList.id)
        .outerjoin(
            issue_identity,
            and_(
                issue_identity.id == CBLSourceEntry.external_issue_identity_id,
                issue_identity.provider == COMICVINE_PROVIDER,
                issue_identity.entity_type == ISSUE_ENTITY_TYPE,
            ),
        )
        .where(
            CBLSourceList.active.is_(True),
            CBLSourceList.id.in_(select(matching_list_ids.c.list_id)),
        )
        .group_by(CBLSourceList.id, CBLSource.id)
        .order_by(CBLSourceList.name.asc(), CBLSourceList.id.asc())
    )
    rows = (await db.execute(statement)).all()
    return tuple(
        CBLSourceCoverageRow(
            source_list=row[0],
            source=row[1],
            entries_total=int(row[2]),
            distinct_source_issues=int(row[3]),
        )
        for row in rows
    )


async def find_matched_cbl_source_entries(
    db: AsyncSession,
    *,
    list_ids: tuple[int, ...],
    comicvine_issue_ids: tuple[str, ...],
) -> tuple[CBLMatchedSourceEntryRow, ...]:
    """Return every matching source occurrence inside the candidate lists.

    The rows keep the source's original position order, including repeated
    occurrences of the same exact issue identity. Volume identity is reported
    as context so callers can render the source without granting ownership.

    Args:
        db: Database session.
        list_ids: Candidate source list IDs.
        comicvine_issue_ids: Distinct exact Comic Vine issue external IDs.

    Returns:
        Matching source occurrences ordered by list, source position, and row ID.
    """
    if not list_ids or not comicvine_issue_ids:
        return ()

    issue_identity = aliased(ExternalIdentity)
    volume_identity = aliased(ExternalIdentity)
    statement = (
        select(
            CBLSourceEntry.list_id,
            CBLSourceEntry.position,
            issue_identity.external_id,
            CBLSourceEntry.series_name,
            CBLSourceEntry.issue_number,
            CBLSourceEntry.volume_year,
            CBLSourceEntry.publication_year,
            volume_identity.external_id,
        )
        .join(
            issue_identity,
            and_(
                issue_identity.id == CBLSourceEntry.external_issue_identity_id,
                issue_identity.provider == COMICVINE_PROVIDER,
                issue_identity.entity_type == ISSUE_ENTITY_TYPE,
            ),
        )
        .outerjoin(
            volume_identity,
            and_(
                volume_identity.id == CBLSourceEntry.external_series_identity_id,
                volume_identity.provider == COMICVINE_PROVIDER,
                volume_identity.entity_type == SERIES_ENTITY_TYPE,
            ),
        )
        .where(
            CBLSourceEntry.list_id.in_(list_ids),
            issue_identity.external_id.in_(comicvine_issue_ids),
        )
        .order_by(
            CBLSourceEntry.list_id.asc(),
            CBLSourceEntry.position.asc(),
            CBLSourceEntry.id.asc(),
        )
    )
    rows = (await db.execute(statement)).all()
    return tuple(
        CBLMatchedSourceEntryRow(
            list_id=int(row[0]),
            position=int(row[1]),
            comicvine_issue_id=str(row[2]),
            series_name=str(row[3]),
            issue_number=str(row[4]),
            volume_year=None if row[5] is None else int(row[5]),
            publication_year=None if row[6] is None else int(row[6]),
            comicvine_volume_id=None if row[7] is None else str(row[7]),
        )
        for row in rows
    )
