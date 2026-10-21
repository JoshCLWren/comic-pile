"""Read-only CBL identity exceptions with owned-candidate choices before import.

Issue #4015 (part of #4003, governed by #1615): the CBL adoption preview must
show the source issue and volume identity, every owned comic that could
satisfy the position, a plain reason when the position could not be matched,
and the explicit choices a reader can make: reuse one owned copy, add the
identified comic as a new one, or leave the position out. An unresolved comic
must never be imported silently, and a comic whose only owned copies belong to
a different volume must never be included without the reader saying so.

This module never writes. It reports facts that the adoption preview renders
and that the adoption commit revalidates before it changes anything. Global
source facts stay untouched: the reader's choices belong to the adoption
review, not to the shared catalog.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSourceEntry
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread

IdentityExceptionState = Literal[
    "resolved",
    "wrong_volume",
    "ambiguous",
    "missing",
    "unidentified",
]

#: Resolution status used when every owned copy belongs to a different volume.
WRONG_VOLUME_STATUS = "cbl_identity_wrong_volume"
#: Resolution status used when several owned copies need an explicit choice.
AMBIGUOUS_CANDIDATES_STATUS = "cbl_identity_ambiguous_candidates"
#: Resolution status used when the exact ComicVine volume settled the match.
VOLUME_RESOLVED_STATUS = "resolved_via_comicvine_volume"


@dataclass(frozen=True)
class CBLIdentityCandidate:
    """One owned Issue that could satisfy a CBL source position."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    series_external_id: str | None
    series_identity_matches_cbl: bool
    series_identity_conflicts: bool
    read_status: str | None
    cover_date: str | None
    volume_id: str | None


@dataclass(frozen=True)
class CBLIdentityException:
    """Identity facts and reader options for one CBL source position."""

    cbl_entry_id: int
    cbl_position: int
    series_name: str
    issue_number: str
    state: IdentityExceptionState
    reason: str
    comicvine_issue_id: str | None
    comicvine_series_id: str | None
    series_provider: str | None
    series_external_id: str | None
    cover_date: str | None
    volume_year: int | None
    publication_year: int | None
    candidates: tuple[CBLIdentityCandidate, ...] = ()
    resolved_issue_id: int | None = None

    @property
    def requires_choice(self) -> bool:
        """Return whether the reader must pick a reuse/new/exclude answer."""
        return self.state in {"wrong_volume", "ambiguous", "unidentified"}

    @property
    def can_reuse(self) -> bool:
        """Return whether at least one owned copy may be reused."""
        return bool(self.candidates)

    @property
    def can_create_new(self) -> bool:
        """Return whether the identified comic may be added as a new copy.

        A new copy is only safe when no owned Issue is already confirmed as
        this ComicVine issue, because a second confirmed copy of the same
        provider identity is a duplicate the reader has not asked for.
        """
        return self.state == "missing" and self.comicvine_issue_id is not None


@dataclass(frozen=True)
class _SourceIdentity:
    """Provider identity metadata for one CBL source position."""

    comicvine_issue_id: str | None
    comicvine_series_id: str | None
    series_provider: str | None
    series_external_id: str | None
    series_identity_id: int | None
    cover_date: str | None
    volume_id: str | None


@dataclass(frozen=True)
class _OwnedCopy:
    """One owned Issue confirmed on a source position's provider identity."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    read_status: str | None


def _metadata_text(metadata: object, key: str) -> str | None:
    """Return a string metadata field when present."""
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    if value is None:
        return None
    return str(value)


def _normalized_volume(external_id: str) -> str:
    """Return a ComicVine volume id without its ``4050-`` URL prefix."""
    return external_id.strip().removeprefix("4050-")


async def _source_identities(
    db: AsyncSession,
    entries: list[CBLSourceEntry],
) -> dict[int, _SourceIdentity]:
    """Return the provider identity metadata for every source position.

    Args:
        db: Async database session.
        entries: Source entries in source order.

    Returns:
        One identity record per source entry id.
    """
    issue_identity_ids = {
        entry.external_issue_identity_id
        for entry in entries
        if entry.external_issue_identity_id is not None
    }
    series_identity_ids = {
        entry.external_series_identity_id
        for entry in entries
        if entry.external_series_identity_id is not None
    }
    identities: dict[int, ExternalIdentity] = {}
    if issue_identity_ids or series_identity_ids:
        result = await db.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.id.in_(issue_identity_ids | series_identity_ids)
            )
        )
        for identity in result.scalars().all():
            identities[identity.id] = identity

    records: dict[int, _SourceIdentity] = {}
    for entry in entries:
        issue_identity = identities.get(entry.external_issue_identity_id or -1)
        series_identity = identities.get(entry.external_series_identity_id or -1)
        series_provider = None if series_identity is None else series_identity.provider
        series_external_id = None if series_identity is None else series_identity.external_id
        comicvine_series_id = (
            series_external_id
            if series_provider is not None and series_provider.casefold() == "comicvine"
            else None
        )
        records[entry.id] = _SourceIdentity(
            comicvine_issue_id=None if issue_identity is None else issue_identity.external_id,
            comicvine_series_id=comicvine_series_id,
            series_provider=series_provider,
            series_external_id=series_external_id,
            series_identity_id=entry.external_series_identity_id,
            cover_date=(
                None
                if issue_identity is None
                else _metadata_text(issue_identity.metadata_json, "cover_date")
            ),
            volume_id=(
                None
                if issue_identity is None
                else _metadata_text(issue_identity.metadata_json, "volume_id")
            ),
        )
    return records


async def _owned_copies(
    db: AsyncSession,
    *,
    user_id: int,
    issue_identity_ids: set[int],
) -> dict[int, list[_OwnedCopy]]:
    """Return every owned copy confirmed on a source position's identity.

    Cross-volume copies are reported instead of being dropped, so the reader
    can see why an entry could not be matched and choose deliberately.

    Args:
        db: Async database session.
        user_id: Issue owner.
        issue_identity_ids: External issue identity ids used by the source.

    Returns:
        Owned copies per external issue identity id.
    """
    if not issue_identity_ids:
        return {}

    rows = (
        await db.execute(
            select(
                IssueExternalIdentityMapping.external_identity_id,
                Issue.id,
                Issue.issue_number,
                Issue.status,
                Thread.id,
                Thread.title,
            )
            .join(
                IssueExternalIdentityMapping,
                IssueExternalIdentityMapping.issue_id == Issue.id,
            )
            .join(Thread, Thread.id == Issue.thread_id)
            .where(
                IssueExternalIdentityMapping.external_identity_id.in_(issue_identity_ids),
                IssueExternalIdentityMapping.status == "confirmed",
                Thread.user_id == user_id,
            )
            .order_by(Issue.id)
        )
    ).all()

    copies: dict[int, list[_OwnedCopy]] = {}
    for row in rows:
        identity_id = int(row[0])
        copies.setdefault(identity_id, []).append(
            _OwnedCopy(
                issue_id=int(row[1]),
                thread_id=int(row[4]),
                thread_title=str(row[5]),
                issue_number=str(row[2]),
                read_status=None if row[3] is None else str(row[3]),
            )
        )
    return copies


async def _series_evidence(
    db: AsyncSession,
    *,
    thread_ids: set[int],
) -> dict[int, list[tuple[int, str]]]:
    """Return the confirmed series identities of every candidate thread.

    Each entry is ``(external_identity_id, external_id)`` for one confirmed
    series mapping of the thread.
    """
    if not thread_ids:
        return {}
    rows = (
        await db.execute(
            select(
                ThreadExternalSeriesMapping.thread_id,
                ThreadExternalSeriesMapping.external_identity_id,
                ExternalIdentity.external_id,
            )
            .join(
                ExternalIdentity,
                ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
            )
            .where(
                ThreadExternalSeriesMapping.thread_id.in_(thread_ids),
                ThreadExternalSeriesMapping.status == "confirmed",
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "series",
            )
        )
    ).all()
    evidence: dict[int, list[tuple[int, str]]] = {}
    for thread_id, identity_id, external_id in rows:
        evidence.setdefault(int(thread_id), []).append((int(identity_id), str(external_id)))
    return evidence


def _candidate_label(candidate: CBLIdentityCandidate) -> str:
    """Return a reader-facing label for one owned candidate."""
    return f"{candidate.thread_title} #{candidate.issue_number}"


def _wrong_volume_reason(
    identity: _SourceIdentity,
    candidates: list[CBLIdentityCandidate],
) -> str:
    """Return the reader-facing reason a volume could not be matched."""
    issue_id = identity.comicvine_issue_id or "this entry"
    volume_id = identity.comicvine_series_id or "the source volume"
    owned = ", ".join(_candidate_label(candidate) for candidate in candidates)
    return (
        f"ComicVine issue {issue_id} belongs to volume {volume_id}, but the only "
        f"comics you own for it are from a different volume ({owned}). "
        "ComicPile will not include a different volume without your choice."
    )


def _ambiguous_reason(
    identity: _SourceIdentity,
    candidates: list[CBLIdentityCandidate],
) -> str:
    """Return the reader-facing reason several owned copies need a choice."""
    issue_id = identity.comicvine_issue_id or "this entry"
    owned = ", ".join(_candidate_label(candidate) for candidate in candidates)
    return (
        f"You own {len(candidates)} copies of ComicVine issue {issue_id} ({owned}). "
        "Choose the copy to reuse, or leave this comic out."
    )


def _unidentified_reason() -> str:
    """Return the reader-facing reason a source position has no identity."""
    return (
        "This source entry has no ComicVine issue ID, so ComicPile cannot confirm "
        "which physical comic it means. Leave it out or fix the source identity."
    )


def _missing_reason(identity: _SourceIdentity) -> str:
    """Return the reader-facing reason an identified comic is not owned yet."""
    issue_id = identity.comicvine_issue_id or "this entry"
    return (
        f"ComicVine issue {issue_id} is not in your collection yet. It is clearly "
        "importable and is only created when you confirm the add."
    )


def _resolved_reason(identity: _SourceIdentity) -> str:
    """Return the reader-facing reason a position matched exactly one comic."""
    issue_id = identity.comicvine_issue_id
    if issue_id is None:
        return "This comic is matched to one comic you already own."
    return f"ComicVine issue {issue_id} matches one comic you already own."


def _volume_match(
    identity: _SourceIdentity,
    thread_series: list[tuple[int, str]],
) -> bool:
    """Return whether a candidate thread carries the source volume identity.

    The exact identity row wins, and an equivalent provider id matches too, so
    a volume stored with its ``4050-`` URL prefix still matches the plain
    series id the shared catalog uses.
    """
    if identity.series_identity_id is not None:
        for mapped_identity_id, _ in thread_series:
            if mapped_identity_id == identity.series_identity_id:
                return True
    cbl_volume = identity.comicvine_series_id
    if cbl_volume is None:
        return False
    for _, external_id in thread_series:
        if _normalized_volume(external_id) == _normalized_volume(cbl_volume):
            return True
    return False


async def build_cbl_identity_exceptions(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    resolved_issue_ids: Mapping[int, int | None] | None = None,
) -> list[CBLIdentityException]:
    """Report the identity facts and reader options for every source position.

    The report is read-only. It never creates, updates, or deletes an Issue,
    Thread, identity, or source row.

    Args:
        db: Async database session.
        user_id: Issue owner whose comics are eligible candidates.
        list_id: Active ``cbl_source_lists`` row.
        resolved_issue_ids: Issue id the reconciliation already chose per
            source entry id. A position that already matched keeps that
            match unless the volume or duplicate evidence contradicts it.

    Returns:
        One identity record per source position, in source order.
    """
    entries = list(
        (
            await db.execute(
                select(CBLSourceEntry)
                .where(CBLSourceEntry.list_id == list_id)
                .order_by(CBLSourceEntry.position, CBLSourceEntry.id)
            )
        )
        .scalars()
        .all()
    )
    if not entries:
        return []

    identities = await _source_identities(db, entries)
    identity_ids = {
        entry.external_issue_identity_id
        for entry in entries
        if entry.external_issue_identity_id is not None
    }
    owned_copies = await _owned_copies(
        db,
        user_id=user_id,
        issue_identity_ids=identity_ids,
    )
    thread_ids = {copy.thread_id for copies in owned_copies.values() for copy in copies}
    series_evidence = await _series_evidence(db, thread_ids=thread_ids)
    reconciled = dict(resolved_issue_ids or {})

    records: list[CBLIdentityException] = []
    for entry in entries:
        identity = identities[entry.id]
        raw_copies = (
            owned_copies.get(entry.external_issue_identity_id or -1, [])
            if entry.external_issue_identity_id is not None
            else []
        )
        candidates: list[CBLIdentityCandidate] = []
        for copy in raw_copies:
            thread_series = series_evidence.get(copy.thread_id, [])
            has_volume_evidence = identity.comicvine_series_id is not None
            matches = has_volume_evidence and _volume_match(identity, thread_series)
            conflicts = (
                has_volume_evidence
                and bool(thread_series)
                and not matches
            )
            candidates.append(
                CBLIdentityCandidate(
                    issue_id=copy.issue_id,
                    thread_id=copy.thread_id,
                    thread_title=copy.thread_title,
                    issue_number=copy.issue_number,
                    series_external_id=(
                        None if not thread_series else thread_series[0][1]
                    ),
                    series_identity_matches_cbl=matches,
                    series_identity_conflicts=conflicts,
                    read_status=copy.read_status,
                    cover_date=identity.cover_date,
                    volume_id=identity.volume_id,
                )
            )

        exact = [candidate for candidate in candidates if candidate.series_identity_matches_cbl]
        conflicting = [
            candidate for candidate in candidates if candidate.series_identity_conflicts
        ]
        already_resolved = reconciled.get(entry.id)

        if identity.comicvine_issue_id is None:
            state: IdentityExceptionState = "unidentified"
            reason = _unidentified_reason()
            resolved_issue_id = None
        elif len(exact) == 1:
            state = "resolved"
            reason = _resolved_reason(identity)
            resolved_issue_id = exact[0].issue_id
        elif len(exact) > 1:
            state = "ambiguous"
            reason = _ambiguous_reason(identity, exact)
            resolved_issue_id = None
        elif len(candidates) > 1:
            state = "ambiguous"
            reason = _ambiguous_reason(identity, candidates)
            resolved_issue_id = None
        elif conflicting:
            state = "wrong_volume"
            reason = _wrong_volume_reason(identity, conflicting)
            resolved_issue_id = None
        elif candidates:
            # The owned copy has no confirmed volume of its own. The ComicVine
            # issue identity stays exact physical identity, so it is reusable.
            state = "resolved"
            reason = _resolved_reason(identity)
            resolved_issue_id = already_resolved or candidates[0].issue_id
        elif already_resolved is not None:
            # The reconciliation matched this position by another route, such
            # as the title and issue number fallback. That match is kept.
            state = "resolved"
            reason = _resolved_reason(identity)
            resolved_issue_id = already_resolved
        else:
            state = "missing"
            reason = _missing_reason(identity)
            resolved_issue_id = None

        records.append(
            CBLIdentityException(
                cbl_entry_id=entry.id,
                cbl_position=entry.position,
                series_name=entry.series_name,
                issue_number=entry.issue_number,
                state=state,
                reason=reason,
                comicvine_issue_id=identity.comicvine_issue_id,
                comicvine_series_id=identity.comicvine_series_id,
                series_provider=identity.series_provider,
                series_external_id=identity.series_external_id,
                cover_date=identity.cover_date,
                volume_year=entry.volume_year,
                publication_year=entry.publication_year,
                candidates=tuple(candidates),
                resolved_issue_id=resolved_issue_id,
            )
        )
    return records


def _exception_fields(exception: CBLIdentityException) -> dict[str, object]:
    """Return the read-only identity facts published for one source position."""
    return {
        "source_identity": {
            "comicvine_issue_id": exception.comicvine_issue_id,
            "comicvine_series_id": exception.comicvine_series_id,
            "series_provider": exception.series_provider,
            "series_external_id": exception.series_external_id,
            "cover_date": exception.cover_date,
            "volume_year": exception.volume_year,
            "publication_year": exception.publication_year,
        },
        "identity_state": exception.state,
        "identity_reason": exception.reason,
        "identity_candidates": [
            {
                "issue_id": candidate.issue_id,
                "thread_id": candidate.thread_id,
                "thread_title": candidate.thread_title,
                "issue_number": candidate.issue_number,
                "series_external_id": candidate.series_external_id,
                "series_identity_matches_cbl": candidate.series_identity_matches_cbl,
                "series_identity_conflicts": candidate.series_identity_conflicts,
                "read_status": candidate.read_status,
                "cover_date": candidate.cover_date,
                "volume_id": candidate.volume_id,
            }
            for candidate in exception.candidates
        ],
        "identity_options": {
            "can_reuse": exception.can_reuse,
            "can_create_new": exception.can_create_new,
            "can_exclude": True,
            "requires_choice": exception.requires_choice,
        },
    }


def apply_identity_exceptions(
    entries: Sequence[Mapping[str, object]],
    exceptions: Sequence[CBLIdentityException],
) -> list[dict[str, object]]:
    """Attach identity facts to reconciled entries and fail closed on unsafe matches.

    A position whose only owned copies belong to a different volume, or whose
    exact identity is held by several owned copies, is not resolved by the
    reconciliation alone. Those positions are reported as exceptions so the
    reader must choose a copy or deliberately leave the comic out.

    Args:
        entries: Reconciled source positions keyed by their raw field names.
        exceptions: Identity records for the same source list.

    Returns:
        New entry dicts carrying the identity facts and the safe resolution.
    """
    by_entry_id = {exception.cbl_entry_id: exception for exception in exceptions}
    annotated: list[dict[str, object]] = []
    for entry in entries:
        updated = dict(entry)
        entry_id = entry.get("cbl_entry_id")
        exception = by_entry_id.get(entry_id) if isinstance(entry_id, int) else None
        if exception is None:
            annotated.append(updated)
            continue
        updated.update(_exception_fields(exception))
        if exception.state == "wrong_volume":
            updated["resolved_issue_id"] = None
            updated["canonical_issue_id"] = None
            updated["resolution_status"] = WRONG_VOLUME_STATUS
        elif exception.state == "ambiguous":
            updated["resolved_issue_id"] = None
            updated["canonical_issue_id"] = None
            updated["resolution_status"] = AMBIGUOUS_CANDIDATES_STATUS
        elif exception.state == "resolved" and exception.resolved_issue_id is not None:
            if updated.get("resolved_issue_id") != exception.resolved_issue_id:
                updated["resolved_issue_id"] = exception.resolved_issue_id
                updated["canonical_issue_id"] = exception.resolved_issue_id
                updated["resolution_status"] = VOLUME_RESOLVED_STATUS
        annotated.append(updated)
    return annotated


def exception_to_dict(exception: CBLIdentityException) -> dict[str, object]:
    """Serialize one identity exception for a read-only report."""
    return {
        "cbl_entry_id": exception.cbl_entry_id,
        "cbl_position": exception.cbl_position,
        "state": exception.state,
        "reason": exception.reason,
        "comicvine_issue_id": exception.comicvine_issue_id,
        "comicvine_series_id": exception.comicvine_series_id,
        "series_provider": exception.series_provider,
        "series_external_id": exception.series_external_id,
        "cover_date": exception.cover_date,
        "volume_year": exception.volume_year,
        "publication_year": exception.publication_year,
        "resolved_issue_id": exception.resolved_issue_id,
        "requires_choice": exception.requires_choice,
        "can_reuse": exception.can_reuse,
        "can_create_new": exception.can_create_new,
        "candidates": [
            {
                "issue_id": candidate.issue_id,
                "thread_id": candidate.thread_id,
                "thread_title": candidate.thread_title,
                "issue_number": candidate.issue_number,
                "series_external_id": candidate.series_external_id,
                "series_identity_matches_cbl": candidate.series_identity_matches_cbl,
                "series_identity_conflicts": candidate.series_identity_conflicts,
                "read_status": candidate.read_status,
                "cover_date": candidate.cover_date,
                "volume_id": candidate.volume_id,
            }
            for candidate in exception.candidates
        ],
    }
