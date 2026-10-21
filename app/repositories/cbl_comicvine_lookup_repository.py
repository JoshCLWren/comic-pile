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
