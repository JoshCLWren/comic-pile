"""CBL reconciliation to canonical physical-issue identity.

Reconciliation resolves every CBL source position to the canonical ComicPile
Issue that represents the same physical comic, preferring ComicVine issue ID
evidence. Thread/position boundaries never define physical identity. Entries
without ComicVine evidence are surfaced as ambiguous rather than silently
skipped or merged via title + issue number.

This is the reusable read-side layer that carries the authoritative CBL source
order through to an owner's canonical ComicPile issues. Every CBL source
position is preserved position-for-position, already-read entries are retained
(never dropped because they were read out of order), and unresolved,
ambiguous, duplicate, and extra memberships are surfaced rather than silently
discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.services.issue_identity_reconciliation import resolve_cbl_entries_to_canonical


@dataclass(frozen=True, slots=True)
class ReconciledEntry:
    """One CBL source position with its canonical resolution and read status.

    Kept for backward compatibility with earlier repair tooling; new code
    should read the dict entries in :class:`CBLReconciliationReport`.
    """

    cbl_position: int
    series_name: str
    issue_number: str
    comicvine_issue_id: str | None
    resolved_issue_id: int | None
    resolution_status: str
    read_status: str
    read_at: datetime | None
    candidates: tuple[int, ...] = ()

    @property
    def display_name(self) -> str:
        """Return a stable series + issue label."""
        return f"{self.series_name} #{self.issue_number}"


@dataclass(frozen=True, slots=True)
class CBLReconciliationReport:
    """Machine-readable comparison for every source position after reconciliation."""

    total_positions: int
    resolved_count: int
    unresolved_count: int
    duplicate_identity_groups: int
    ambiguous_count: int
    entries: tuple[dict[str, object], ...]
    first_unread_position: int | None
    first_unread_entry: dict[str, object] | None
    # Extended fields for the Ultimate Universe repair verification (issue #2048).
    source_list_id: int | None = None
    source_repository: str | None = None
    source_path: str | None = None
    declared_issue_count: int | None = None
    missing_source_entries: tuple[int, ...] = ()
    extra_member_issue_ids: tuple[int, ...] = ()
    ambiguous_mappings: tuple[int, ...] = ()
    duplicate_identity_issues: tuple[int, ...] = ()
    first_unread_issue_id: int | None = None


async def reconcile_cbl_source_list(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int | None = None,
    source_list_id: int | None = None,
    baseline_member_issue_ids: tuple[int, ...] = (),
) -> CBLReconciliationReport:
    """Reconcile one CBL source list to canonical physical-issue identities.

    Uses the canonical resolution helper so CBL entries that carry a ComicVine
    issue ID always resolve to the history-preserving canonical Issue rather
    than whichever duplicate happens to hold the external mapping.

    Args:
        db: Async database session.
        user_id: Owner user ID whose issues are eligible for matching.
        list_id: CBLSourceList identifier to reconcile (canonical name).
        source_list_id: Legacy alias for ``list_id`` (kept for repair tooling).
        baseline_member_issue_ids: Optional existing crossover member issue ids
            used to detect members that are not present anywhere in the source
            (extra members).

    Returns:
        Structured reconciliation report including the first unread ordered entry
        after overlaying actual read history. When a source list is known, the
        report also carries source metadata and verification aggregates
        (missing/extra/ambiguous/duplicate).

    Raises:
        ValueError: If the source list does not exist or is not active.
    """
    effective_list_id = source_list_id if source_list_id is not None else list_id
    if effective_list_id is None:
        raise TypeError("reconcile_cbl_source_list requires list_id or source_list_id")

    # Validate and load source metadata for the extended report.
    list_row = await db.get(CBLSourceList, effective_list_id)
    if list_row is None or not list_row.active:
        raise ValueError(f"CBL source list {effective_list_id} not found or not active")
    source = await db.get(CBLSource, list_row.source_id) if list_row.source_id else None

    result = await db.execute(
        select(CBLSourceEntry)
        .where(CBLSourceEntry.list_id == effective_list_id)
        .order_by(CBLSourceEntry.position)
    )
    entries = list(result.scalars().all())
    if not entries:
        # No positions but still return a valid report with source metadata.
        return CBLReconciliationReport(
            total_positions=0,
            resolved_count=0,
            unresolved_count=0,
            duplicate_identity_groups=0,
            ambiguous_count=0,
            entries=(),
            first_unread_position=None,
            first_unread_entry=None,
            source_list_id=effective_list_id,
            source_repository=source.repository if source is not None else None,
            source_path=list_row.source_path,
            declared_issue_count=list_row.declared_issue_count,
            missing_source_entries=(),
            extra_member_issue_ids=tuple(sorted(baseline_member_issue_ids)),
            ambiguous_mappings=(),
            duplicate_identity_issues=(),
            first_unread_issue_id=None,
        )

    # Resolve external identity ids to external_id strings where available.
    from app.models.external_identity import ExternalIdentity

    identity_ids = {
        entry.external_issue_identity_id
        for entry in entries
        if entry.external_issue_identity_id is not None
    }
    external_by_id: dict[int, str] = {}
    if identity_ids:
        id_result = await db.execute(
            select(ExternalIdentity.id, ExternalIdentity.external_id).where(
                ExternalIdentity.id.in_(identity_ids)
            )
        )
        external_by_id = {row[0]: row[1] for row in id_result.all()}

    normalized: list[dict[str, object]] = []
    for entry in entries:
        cvid: str | None = None
        if entry.external_issue_identity_id is not None:
            cvid = external_by_id.get(entry.external_issue_identity_id)
        normalized.append(
            {
                "position": entry.position,
                "series_name": entry.series_name,
                "issue_number": entry.issue_number,
                "comicvine_issue_id": cvid,
                "external_issue_identity_id": entry.external_issue_identity_id,
                "external_series_identity_id": entry.external_series_identity_id,
                "cbl_entry_id": entry.id,
                "volume_year": entry.volume_year,
                "publication_year": entry.publication_year,
            }
        )

    resolved = await resolve_cbl_entries_to_canonical(
        db, user_id=user_id, cbl_entries=normalized
    )

    report_entries: list[dict[str, object]] = []
    resolved_count = 0
    unresolved_count = 0
    ambiguous_count = 0
    duplicate_groups = 0
    seen_duplicate_cvids: set[str] = set()

    for norm, canon in zip(normalized, resolved, strict=True):
        is_resolved = canon.resolved_issue_id is not None
        if is_resolved:
            resolved_count += 1
        else:
            unresolved_count += 1
        if canon.resolution_status in (
            "ambiguous_no_comicvine_id",
            "comicvine_identity_not_known",
        ):
            ambiguous_count += 1
        if canon.is_duplicate_identity and canon.comicvine_issue_id:
            if canon.comicvine_issue_id not in seen_duplicate_cvids:
                seen_duplicate_cvids.add(canon.comicvine_issue_id)
                duplicate_groups += 1
        report_entries.append(
            {
                "cbl_position": canon.cbl_position,
                "series_name": canon.cbl_series_name,
                "issue_number": canon.cbl_issue_number,
                "comicvine_issue_id": canon.comicvine_issue_id,
                "external_issue_identity_id": norm.get("external_issue_identity_id"),
                "external_series_identity_id": norm.get("external_series_identity_id"),
                "cbl_entry_id": norm.get("cbl_entry_id"),
                "resolved_issue_id": canon.resolved_issue_id,
                "canonical_issue_id": canon.canonical_issue_id,
                "resolution_status": canon.resolution_status,
                "is_duplicate_identity": canon.is_duplicate_identity,
                "read_status": canon.read_status,
                "read_at": canon.read_at.isoformat() if canon.read_at else None,
            }
        )

    # First unread ordered entry after overlaying actual read history.
    first_unread_position: int | None = None
    first_unread_entry: dict[str, object] | None = None
    for entry in report_entries:
        if (
            entry.get("read_status") == "unread"
            and entry.get("resolved_issue_id") is not None
        ):
            first_unread_position = cast(int, entry["cbl_position"])
            first_unread_entry = entry
            break
        if entry.get("resolved_issue_id") is None:
            continue

    # Extended aggregates for the verification report.
    missing_clean: list[int] = []
    ambiguous_clean: list[int] = []
    duplicate_identity_issues: set[int] = set()
    for entry in report_entries:
        status = entry.get("resolution_status")
        pos = cast(int, entry["cbl_position"])
        if status in (
            "ambiguous_no_comicvine_id",
            "comicvine_identity_not_known",
        ):
            ambiguous_clean.append(pos)
        elif entry.get("resolved_issue_id") is None:
            missing_clean.append(pos)
        if entry.get("is_duplicate_identity"):
            canonical_id = entry.get("canonical_issue_id") or entry.get(
                "resolved_issue_id"
            )
            if isinstance(canonical_id, int):
                duplicate_identity_issues.add(canonical_id)

    resolved_ids = {
        int(entry["resolved_issue_id"])
        for entry in report_entries
        if entry.get("resolved_issue_id") is not None
    }
    for entry in report_entries:
        if (
            entry.get("is_duplicate_identity")
            and entry.get("canonical_issue_id") is not None
        ):
            resolved_ids.add(
                cast(int, entry["canonical_issue_id"])
            )
    extra = tuple(
        sorted(issue_id for issue_id in baseline_member_issue_ids if issue_id not in resolved_ids)
    )

    first_unread_issue_id = (
        cast(int, first_unread_entry["resolved_issue_id"])
        if first_unread_entry
        and first_unread_entry.get("resolved_issue_id") is not None
        else None
    )

    return CBLReconciliationReport(
        total_positions=len(report_entries),
        resolved_count=resolved_count,
        unresolved_count=unresolved_count,
        duplicate_identity_groups=duplicate_groups,
        ambiguous_count=ambiguous_count,
        entries=tuple(report_entries),
        first_unread_position=first_unread_position,
        first_unread_entry=first_unread_entry,
        source_list_id=effective_list_id,
        source_repository=source.repository if source is not None else None,
        source_path=list_row.source_path,
        declared_issue_count=list_row.declared_issue_count,
        missing_source_entries=tuple(sorted(missing_clean)),
        extra_member_issue_ids=extra,
        ambiguous_mappings=tuple(sorted(ambiguous_clean)),
        duplicate_identity_issues=tuple(sorted(duplicate_identity_issues)),
        first_unread_issue_id=first_unread_issue_id,
    )
