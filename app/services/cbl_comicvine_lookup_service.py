"""Read-only reverse lookup of CBL sources by exact Comic Vine issue identity.

This service answers one question: which shared CBL source lists contain a
given exact Comic Vine issue identity, and at which source positions?

The answer never depends on the caller. It never reads reader-owned Issues,
identity mappings, read state, or adoption state, and it never writes to any
table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.cbl_comicvine_lookup_repository import (
    CBLMatchedSourceEntryRow,
    CBLSourceCoverageRow,
    find_cbl_source_coverage_candidates,
    find_matched_cbl_source_entries,
    find_cbl_source_occurrences_by_comicvine_issue as find_occurrence_rows,
)
from app.repositories.issue_identity_repository import (
    find_confirmed_comicvine_issue_identities,
)
from app.services.cbl_source_public import (
    public_cbl_repository,
    public_cbl_source_path,
    public_cbl_source_ref,
)
from app.services.custom_cbl import get_custom_cbl_response


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


@dataclass(frozen=True, slots=True)
class CBLSourceComparisonMatch:
    """Distinct coverage and relative order for one shared CBL source list."""

    list_id: int
    list_name: str
    source_path: str
    source_repository: str
    source_ref: str
    revision_sha: str
    declared_issue_count: int | None
    entries_total: int
    distinct_source_issues: int
    matched_input_count: int
    input_total: int
    matched_occurrence_count: int
    duplicate_match_count: int
    source_only_issue_count: int
    input_coverage_percentage: int
    source_coverage_percentage: int
    order_status: Literal["same_order", "reordered", "not_comparable"]
    order_pair_count: int
    order_disagreement_count: int
    matched_input_ids: tuple[str, ...]
    missing_input_ids: tuple[str, ...]
    score: int


@dataclass(frozen=True, slots=True)
class CBLSourceComparisonPage:
    """Ranked source comparisons for one distinct confirmed input set."""

    comicvine_issue_ids: tuple[str, ...]
    input_total: int
    candidates_total: int
    candidates: tuple[CBLSourceComparisonMatch, ...]


@dataclass(frozen=True, slots=True)
class CBLReadingListEntryIdentity:
    """One Reading List entry plus its confirmed identity or explicit gap."""

    position: int
    issue_id: int
    series_name: str
    issue_number: str
    comicvine_issue_id: str | None
    comicvine_issue_ids: tuple[str, ...]
    identity_status: Literal["confirmed", "missing", "conflict"]


@dataclass(frozen=True, slots=True)
class CBLReadingListCandidates:
    """Reading List identity gaps plus ranked source comparisons."""

    list_id: int
    list_name: str
    input_entry_count: int
    input_confirmed_total: int
    input_missing_count: int
    input_conflict_count: int
    input_ids: tuple[str, ...]
    entries: tuple[CBLReadingListEntryIdentity, ...]
    candidates_total: int
    candidates: tuple[CBLSourceComparisonMatch, ...]


def _distinct_ids(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Trim, skip blanks, and de-duplicate IDs while preserving order.

    Args:
        values: Raw external issue IDs in caller order.

    Returns:
        Distinct non-blank IDs in first-occurrence order.
    """
    distinct: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        distinct.append(value)
    return tuple(distinct)


def _order_disagreements(
    input_ids: tuple[str, ...],
    matched_rows: tuple[CBLMatchedSourceEntryRow, ...],
) -> tuple[int, int]:
    """Count matched comic pairs whose source order differs from input order.

    Duplicate occurrences of one distinct comic never count twice. Only
    distinct matched comics participate, so a source with ``A, A, B`` compares
    as ``A, B`` against the input list.

    Args:
        input_ids: Distinct input IDs in the caller's intended order.
        matched_rows: Matching source occurrences in source order.

    Returns:
        ``(comparable_pair_count, disagreement_count)``.
    """
    input_position = {issue_id: index for index, issue_id in enumerate(input_ids)}
    distinct_source_ids: list[str] = []
    seen: set[str] = set()
    for row in matched_rows:
        if row.comicvine_issue_id in seen:
            continue
        seen.add(row.comicvine_issue_id)
        distinct_source_ids.append(row.comicvine_issue_id)

    positions = [
        input_position[issue_id]
        for issue_id in distinct_source_ids
        if issue_id in input_position
    ]
    pair_count = 0
    disagreement_count = 0
    for left_index, left_position in enumerate(positions):
        for right_position in positions[left_index + 1 :]:
            pair_count += 1
            if left_position > right_position:
                disagreement_count += 1
    return pair_count, disagreement_count


def _comparison_match(
    coverage_row: CBLSourceCoverageRow,
    matched_rows: tuple[CBLMatchedSourceEntryRow, ...],
    input_ids: tuple[str, ...],
) -> CBLSourceComparisonMatch:
    """Score one candidate source against the distinct input comic set.

    Args:
        coverage_row: Aggregate candidate source row.
        matched_rows: Matching source occurrences in source position order.
        input_ids: Distinct input IDs in the caller's intended order.

    Returns:
        A complete coverage/order comparison for the source list.
    """
    source_list = coverage_row.source_list
    source = coverage_row.source
    matched_distinct: list[str] = []
    matched_seen: set[str] = set()
    for row in matched_rows:
        if row.comicvine_issue_id in matched_seen:
            continue
        matched_seen.add(row.comicvine_issue_id)
        matched_distinct.append(row.comicvine_issue_id)

    matched_input_ids = tuple(issue_id for issue_id in input_ids if issue_id in matched_seen)
    missing_input_ids = tuple(issue_id for issue_id in input_ids if issue_id not in matched_seen)
    matched_count = len(matched_input_ids)
    input_total = len(input_ids)
    input_coverage = matched_count / input_total if input_total else 0.0
    source_coverage = (
        matched_count / coverage_row.distinct_source_issues
        if coverage_row.distinct_source_issues
        else 0.0
    )

    pair_count, disagreement_count = _order_disagreements(input_ids, matched_rows)
    order_agreement = (
        1.0 if pair_count == 0 else 1.0 - (disagreement_count / pair_count)
    )
    score = round(
        (55.0 * input_coverage) + (25.0 * source_coverage) + (20.0 * order_agreement)
    )

    order_status: Literal["same_order", "reordered", "not_comparable"]
    if matched_count < 2:
        order_status = "not_comparable"
    elif disagreement_count > 0:
        order_status = "reordered"
    else:
        order_status = "same_order"

    return CBLSourceComparisonMatch(
        list_id=source_list.id,
        list_name=source_list.name,
        source_path=public_cbl_source_path(source_list.source_path),
        source_repository=public_cbl_repository(source.repository),
        source_ref=public_cbl_source_ref(source.repository, source_list.source_path),
        revision_sha=source_list.revision_sha,
        declared_issue_count=source_list.declared_issue_count,
        entries_total=coverage_row.entries_total,
        distinct_source_issues=coverage_row.distinct_source_issues,
        matched_input_count=matched_count,
        input_total=input_total,
        matched_occurrence_count=len(matched_rows),
        duplicate_match_count=max(0, len(matched_rows) - matched_count),
        source_only_issue_count=max(
            0, coverage_row.distinct_source_issues - matched_count
        ),
        input_coverage_percentage=round(100 * input_coverage),
        source_coverage_percentage=round(100 * source_coverage),
        order_status=order_status,
        order_pair_count=pair_count,
        order_disagreement_count=disagreement_count,
        matched_input_ids=matched_input_ids,
        missing_input_ids=missing_input_ids,
        score=score,
    )


async def compare_cbl_sources_by_comicvine_issues(
    db: AsyncSession,
    *,
    comicvine_issue_ids: tuple[str, ...] | list[str],
    limit: int = 50,
) -> CBLSourceComparisonPage:
    """Rank shared CBL source lists by distinct coverage and relative order.

    The comparison is exact-ID only, so same-titled volumes and same-numbered
    issues in another volume never count as matches. Coverage is measured from
    distinct source identities; repeated source occurrences are reported but
    never inflate the matched comic count. Ranking balances input coverage,
    source precision, and order agreement so a gigantic catch-all source does
    not win merely by containing more raw matches.

    Args:
        db: Database session.
        comicvine_issue_ids: Confirmed Comic Vine issue IDs in intended order.
        limit: Maximum number of ranked source lists to return.

    Returns:
        Ranked source comparisons plus the whole-candidate count.
    """
    input_ids = _distinct_ids(tuple(comicvine_issue_ids))
    if not input_ids:
        return CBLSourceComparisonPage(
            comicvine_issue_ids=(),
            input_total=0,
            candidates_total=0,
            candidates=(),
        )

    coverage_rows = await find_cbl_source_coverage_candidates(
        db,
        comicvine_issue_ids=input_ids,
    )
    list_ids = tuple(row.source_list.id for row in coverage_rows)
    matched_rows = await find_matched_cbl_source_entries(
        db,
        list_ids=list_ids,
        comicvine_issue_ids=input_ids,
    )
    rows_by_list: dict[int, list[CBLMatchedSourceEntryRow]] = {}
    for row in matched_rows:
        rows_by_list.setdefault(row.list_id, []).append(row)

    comparisons = [
        _comparison_match(
            coverage_row,
            tuple(rows_by_list.get(coverage_row.source_list.id, ())),
            input_ids,
        )
        for coverage_row in coverage_rows
    ]
    comparisons.sort(
        key=lambda match: (
            -match.score,
            -match.matched_input_count,
            -match.source_coverage_percentage,
            match.list_name,
            match.list_id,
        )
    )
    bounded_limit = max(0, limit)
    return CBLSourceComparisonPage(
        comicvine_issue_ids=input_ids,
        input_total=len(input_ids),
        candidates_total=len(comparisons),
        candidates=tuple(comparisons[:bounded_limit]),
    )


async def get_reading_list_cbl_candidates(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    limit: int = 50,
) -> CBLReadingListCandidates:
    """Compare one owned Reading List's confirmed identities to shared CBLs.

    Entries without a confirmed Comic Vine issue ID, and entries whose local
    Issue has conflicting confirmed IDs, are reported as gaps. They are never
    guessed by title or issue number, and they never turn an otherwise empty
    comparison into a false "no CBL exists" claim.

    Args:
        db: Database session.
        user_id: Owner of the Reading List.
        list_id: Owned Reading List identifier.
        limit: Maximum number of ranked source lists to return.

    Returns:
        Every list entry's identity state plus ranked source comparisons.

    Raises:
        HTTPException: 404 when the list is missing or not owned by the reader.
    """
    reading_list = await get_custom_cbl_response(db, user_id=user_id, list_id=list_id)
    issue_ids = tuple(entry.issue_id for entry in reading_list.entries)
    identity_rows = await find_confirmed_comicvine_issue_identities(
        db,
        user_id=user_id,
        issue_ids=issue_ids,
    )
    identities_by_issue: dict[int, list[str]] = {}
    for identity in identity_rows:
        identities_by_issue.setdefault(identity.issue_id, []).append(
            identity.comicvine_issue_id
        )

    entries: list[CBLReadingListEntryIdentity] = []
    input_ids: list[str] = []
    seen_input_ids: set[str] = set()
    missing_count = 0
    conflict_count = 0
    for entry in reading_list.entries:
        confirmed_ids = tuple(identities_by_issue.get(entry.issue_id, ()))
        identity_status: Literal["confirmed", "missing", "conflict"]
        if len(confirmed_ids) == 0:
            identity_status = "missing"
            missing_count += 1
        elif len(confirmed_ids) == 1:
            identity_status = "confirmed"
            if confirmed_ids[0] not in seen_input_ids:
                seen_input_ids.add(confirmed_ids[0])
                input_ids.append(confirmed_ids[0])
        else:
            identity_status = "conflict"
            conflict_count += 1
        entries.append(
            CBLReadingListEntryIdentity(
                position=entry.position,
                issue_id=entry.issue_id,
                series_name=entry.series_name,
                issue_number=entry.issue_number,
                comicvine_issue_id=(
                    confirmed_ids[0] if len(confirmed_ids) == 1 else None
                ),
                comicvine_issue_ids=confirmed_ids,
                identity_status=identity_status,
            )
        )

    comparison = await compare_cbl_sources_by_comicvine_issues(
        db,
        comicvine_issue_ids=tuple(input_ids),
        limit=limit,
    )
    return CBLReadingListCandidates(
        list_id=reading_list.id,
        list_name=reading_list.name,
        input_entry_count=len(reading_list.entries),
        input_confirmed_total=len(input_ids),
        input_missing_count=missing_count,
        input_conflict_count=conflict_count,
        input_ids=tuple(input_ids),
        entries=tuple(entries),
        candidates_total=comparison.candidates_total,
        candidates=comparison.candidates,
    )


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
