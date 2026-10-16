"""Report CBL entry → owned Issue identity resolution without applying a plan.

Imported X-Men Era Ten and Fantastic Four Early Years lists must not be
adopted while entries are unmatched or multi-matched. This helper never
omits unresolved positions and never picks the lowest issue id when several
owned comics share an external identity. It does not insert ContinuityPlans.

# Issue #3470: ComicVine external series + issue identity takes precedence.
# Do not resolve 1988 Forever People to 1971 The Forever People by near-equal
title/issue number; distinct external_series_identity_id must stay distinct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSourceEntry, CBLSourceList
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread

ResolutionStatus = Literal[
    "unique_confirmed_identity",
    "resolved_comicvine_volume",
    "ambiguous_duplicate_copies",
    "unmatched",
    "missing_external_identity",
]


class CblIdentityResolutionError(ValueError):
    """Raised when a CBL list cannot be inspected."""


@dataclass(frozen=True)
class IdentityCandidate:
    """One owned Issue that shares a CBL entry's ComicVine identity."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    series_external_id: str | None
    series_identity_matches_cbl: bool
    cover_date: str | None
    volume_id: str | None


@dataclass
class IdentityResolutionRow:
    """One CBL position with every candidate and the evidence decision."""

    list_id: int
    position: int
    series_name: str
    issue_number: str
    volume_year: int | None
    publication_year: int | None
    comicvine_issue_id: str | None
    comicvine_series_id: str | None
    cover_date: str | None
    volume_id: str | None
    status: ResolutionStatus
    chosen_issue_id: int | None
    evidence: str
    classification: Literal["a", "b", "c"]
    candidates: list[IdentityCandidate] = field(default_factory=list)


def _metadata_text(metadata: object, key: str) -> str | None:
    """Return a string metadata field when present."""
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    if value is None:
        return None
    return str(value)


async def report_cbl_source_identity_resolution(
    db: AsyncSession,
    *,
    user_id: int,
    source_list_id: int,
) -> list[IdentityResolutionRow]:
    """Resolve every CBL entry in source order from ComicVine evidence.

    Unique confirmed mappings are accepted. When several owned Issues share
    the identity, the ComicVine volume on the Thread wins only if exactly one
    candidate matches the CBL series identity. Duplicate copies of that same
    volume stay ambiguous. Unmatched entries are reported with empty
    candidates.

    Args:
        db: Async database session. Caller must not commit plan writes.
        user_id: Issue owner.
        source_list_id: Active ``cbl_source_lists`` row.

    Returns:
        One row per CBL position, in source order.

    Raises:
        CblIdentityResolutionError: When the list is missing or inactive.
    """
    source_list = await db.get(CBLSourceList, source_list_id)
    if source_list is None or not source_list.active:
        raise CblIdentityResolutionError("CBL source list is missing or inactive")
    entries = list(
        (
            await db.execute(
                select(CBLSourceEntry)
                .where(CBLSourceEntry.list_id == source_list_id)
                .order_by(CBLSourceEntry.position, CBLSourceEntry.id)
            )
        ).scalars().all()
    )
    rows: list[IdentityResolutionRow] = []
    for entry in entries:
        rows.append(await _resolve_entry(db, user_id=user_id, entry=entry))
    return rows


def resolution_is_complete(rows: list[IdentityResolutionRow]) -> bool:
    """Return whether every entry has exactly one evidence-backed Issue."""
    return all(row.chosen_issue_id is not None for row in rows)


async def _resolve_entry(
    db: AsyncSession,
    *,
    user_id: int,
    entry: CBLSourceEntry,
) -> IdentityResolutionRow:
    """Classify one CBL position against owned confirmed mappings."""
    issue_identity: ExternalIdentity | None = None
    series_identity: ExternalIdentity | None = None
    if entry.external_issue_identity_id is not None:
        issue_identity = await db.get(ExternalIdentity, entry.external_issue_identity_id)
    if entry.external_series_identity_id is not None:
        series_identity = await db.get(ExternalIdentity, entry.external_series_identity_id)
    comicvine_issue_id = None if issue_identity is None else issue_identity.external_id
    comicvine_series_id = None if series_identity is None else series_identity.external_id
    cover_date = None if issue_identity is None else _metadata_text(
        issue_identity.metadata_json, "cover_date"
    )
    volume_id = None if issue_identity is None else _metadata_text(
        issue_identity.metadata_json, "volume_id"
    )
    if volume_id is None:
        volume_id = comicvine_series_id
    candidates = await _candidates_for_entry(db, user_id=user_id, entry=entry)
    base = IdentityResolutionRow(
        list_id=entry.list_id,
        position=entry.position,
        series_name=entry.series_name,
        issue_number=entry.issue_number,
        volume_year=entry.volume_year,
        publication_year=entry.publication_year,
        comicvine_issue_id=comicvine_issue_id,
        comicvine_series_id=comicvine_series_id,
        cover_date=cover_date,
        volume_id=volume_id,
        status="unmatched",
        chosen_issue_id=None,
        evidence="",
        classification="c",
        candidates=candidates,
    )
    if entry.external_issue_identity_id is None:
        base.status = "missing_external_identity"
        base.evidence = "CBL entry has no ComicVine issue identity"
        return base
    if not candidates:
        base.status = "unmatched"
        base.evidence = (
            "no owned confirmed mapping for ComicVine issue "
            f"{comicvine_issue_id}; not omitted"
        )
        return base
    if len(candidates) == 1:
        chosen = candidates[0]
        base.status = "unique_confirmed_identity"
        base.chosen_issue_id = chosen.issue_id
        base.classification = "a"
        base.evidence = (
            f"single owned confirmed mapping to ComicVine issue {comicvine_issue_id}"
        )
        return base
    volume_hits = [cand for cand in candidates if cand.series_identity_matches_cbl]
    if len(volume_hits) == 1:
        chosen = volume_hits[0]
        base.status = "resolved_comicvine_volume"
        base.chosen_issue_id = chosen.issue_id
        base.classification = "a"
        base.evidence = (
            "exactly one candidate Thread maps to CBL ComicVine volume "
            f"{comicvine_series_id}; rejected "
            + ", ".join(
                f"{cand.thread_title} #{cand.issue_number}"
                for cand in candidates
                if cand.issue_id != chosen.issue_id
            )
        )
        return base
    base.status = "ambiguous_duplicate_copies"
    base.evidence = (
        "several owned Issues share ComicVine issue "
        f"{comicvine_issue_id} on the same volume; "
        "not selecting the lowest issue id"
    )
    return base


async def _candidates_for_entry(
    db: AsyncSession,
    *,
    user_id: int,
    entry: CBLSourceEntry,
) -> list[IdentityCandidate]:
    """Return every owned confirmed mapping for one CBL identity."""
    if entry.external_issue_identity_id is None:
        return []
    mapped = list(
        (
            await db.execute(
                select(Issue, Thread, IssueExternalIdentityMapping)
                .join(
                    IssueExternalIdentityMapping,
                    IssueExternalIdentityMapping.issue_id == Issue.id,
                )
                .join(Thread, Thread.id == Issue.thread_id)
                .where(
                    IssueExternalIdentityMapping.external_identity_id
                    == entry.external_issue_identity_id,
                    IssueExternalIdentityMapping.status == "confirmed",
                    Thread.user_id == user_id,
                )
                .order_by(Thread.id, Issue.id)
            )
        ).all()
    )
    candidates: list[IdentityCandidate] = []
    seen_issue_ids: set[int] = set()
    issue_identity = await db.get(ExternalIdentity, entry.external_issue_identity_id)
    cover_date = None if issue_identity is None else _metadata_text(
        issue_identity.metadata_json, "cover_date"
    )
    volume_id = None if issue_identity is None else _metadata_text(
        issue_identity.metadata_json, "volume_id"
    )
    for issue, thread, _mapping in mapped:
        if issue.id in seen_issue_ids:
            continue
        seen_issue_ids.add(issue.id)
        series_external_id, matches = await _thread_series_match(
            db,
            thread_id=thread.id,
            cbl_series_identity_id=entry.external_series_identity_id,
        )
        # Issue #3470: if CBL provides a series identity and the thread does not
        # match it exactly, do not guess by title/issue number across volumes.
        if (
            entry.external_series_identity_id is not None
            and not matches
            and series_external_id is not None
        ):
            # Cross-volume: skip this candidate rather than collapse 1971/1988.
            continue
        candidates.append(
            IdentityCandidate(
                issue_id=issue.id,
                thread_id=thread.id,
                thread_title=thread.title,
                issue_number=issue.issue_number,
                series_external_id=series_external_id,
                series_identity_matches_cbl=matches,
                cover_date=cover_date,
                volume_id=volume_id,
            )
        )
    return candidates


def row_to_dict(row: IdentityResolutionRow) -> dict[str, object]:
    """Serialize one resolution row for a read-only report."""
    return {
        "list_id": row.list_id,
        "position": row.position,
        "series_name": row.series_name,
        "issue_number": row.issue_number,
        "volume_year": row.volume_year,
        "publication_year": row.publication_year,
        "comicvine_issue_id": row.comicvine_issue_id,
        "comicvine_series_id": row.comicvine_series_id,
        "cover_date": row.cover_date,
        "volume_id": row.volume_id,
        "status": row.status,
        "chosen_issue_id": row.chosen_issue_id,
        "evidence": row.evidence,
        "classification": row.classification,
        "candidates": [
            {
                "issue_id": candidate.issue_id,
                "thread_id": candidate.thread_id,
                "thread_title": candidate.thread_title,
                "issue_number": candidate.issue_number,
                "series_external_id": candidate.series_external_id,
                "series_identity_matches_cbl": candidate.series_identity_matches_cbl,
                "cover_date": candidate.cover_date,
                "volume_id": candidate.volume_id,
            }
            for candidate in row.candidates
        ],
    }


async def _thread_series_match(
    db: AsyncSession,
    *,
    thread_id: int,
    cbl_series_identity_id: int | None,
) -> tuple[str | None, bool]:
    """Return the Thread's top series identity and whether any mapping is the CBL volume."""
    mappings = list(
        (
            await db.execute(
                select(ThreadExternalSeriesMapping)
                .where(ThreadExternalSeriesMapping.thread_id == thread_id)
                .order_by(
                    ThreadExternalSeriesMapping.confidence.desc(),
                    ThreadExternalSeriesMapping.id,
                )
            )
        ).scalars().all()
    )
    if not mappings:
        return None, False
    identity = await db.get(ExternalIdentity, mappings[0].external_identity_id)
    external_id = None if identity is None else identity.external_id
    matches = (
        cbl_series_identity_id is not None
        and any(mapping.external_identity_id == cbl_series_identity_id for mapping in mappings)
    )
    return external_id, matches
