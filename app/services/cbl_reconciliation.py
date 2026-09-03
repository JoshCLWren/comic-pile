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
import hashlib
import re
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
    content_hash: str | None = None
    revision_sha: str | None = None
    declared_issue_count: int | None = None
    missing_source_entries: tuple[int, ...] = ()
    extra_member_issue_ids: tuple[int, ...] = ()
    ambiguous_mappings: tuple[int, ...] = ()
    duplicate_identity_issues: tuple[int, ...] = ()
    first_unread_issue_id: int | None = None


@dataclass(frozen=True, slots=True)
class CBLAdoptionPlan:
    """Read-only adoption decisions for every CBL source position."""

    entries: tuple[dict[str, object], ...]
    reused_existing_count: int
    missing_would_create_count: int
    excluded_count: int
    unresolved_count: int
    final_adopted_count: int
    final_adopted_order: tuple[int, ...]


def cbl_series_group_id(entry: dict[str, object]) -> str:
    """Return a deterministic series/run grouping key for a CBL entry.

    ComicVine series identity is preferred. Legacy CBL entries without that
    identity use normalized source name and volume/publication year, so the
    representation remains usable for user-provided CBL input.
    """
    external_series_id = entry.get("series_external_id") or entry.get("comicvine_series_id")
    if external_series_id is not None:
        provider = str(entry.get("series_provider") or "comicvine").strip().casefold()
        return f"provider-series:{provider}:{external_series_id}"
    name = re.sub(r"\s+", " ", str(entry.get("series_name") or "").strip().casefold())
    year = entry.get("volume_year") or entry.get("publication_year") or "unknown"
    digest = hashlib.sha256(f"{name}|{year}".encode()).hexdigest()[:16]
    return f"source-series:{digest}"


def cbl_comicvine_series_id(entry: dict[str, object]) -> str | None:
    """Return a series ID only when the provider is ComicVine."""
    provider = str(entry.get("series_provider") or "").strip().casefold()
    external_id = entry.get("series_external_id")
    return str(external_id) if provider == "comicvine" and external_id is not None else None


def calculate_cbl_adoption_plan(
    entries: tuple[dict[str, object], ...] | list[dict[str, object]],
    *,
    series_decisions: dict[str, bool] | None = None,
    entry_decisions: dict[str, bool] | None = None,
) -> CBLAdoptionPlan:
    """Calculate an adoption plan without database or persistence access.

    Existing entries are included by default. Missing/importable entries require
    an explicit entry or series include decision. Unresolved/ambiguous entries
    are never adopted. An entry decision overrides its series decision.
    """
    series_choices = {str(key): value for key, value in (series_decisions or {}).items()}
    entry_choices = {str(key): value for key, value in (entry_decisions or {}).items()}
    planned: list[dict[str, object]] = []
    adopted_positions: list[int] = []
    reused = missing = excluded = unresolved = 0

    for source_entry in entries:
        entry = dict(source_entry)
        position = int(entry["cbl_position"])
        series_group_id = str(entry.get("series_group_id") or cbl_series_group_id(entry))
        entry_key = str(entry.get("cbl_entry_id") or position)
        resolution_status = str(entry.get("resolution_status") or "")
        ambiguous_canonical = resolution_status == "resolved_via_comicvine_canonical_ambiguous"
        resolved = entry.get("resolved_issue_id") is not None and not ambiguous_canonical
        importable = entry.get("resolution_status") == "no_owned_issue_for_comicvine_id"
        selectable = resolved or importable
        entry["adoption_class"] = (
            "existing"
            if resolved
            else "missing_importable"
            if importable
            else "ambiguous_unresolved"
        )
        if not selectable:
            decision = "unresolved"
            unresolved += 1
        else:
            default_selected = resolved
            selected = entry_choices.get(
                entry_key,
                series_choices.get(series_group_id, default_selected),
            )
            if selected:
                decision = "included_existing" if resolved else "would_create_missing"
                adopted_positions.append(position)
                if resolved:
                    reused += 1
                else:
                    missing += 1
            else:
                explicit = entry_key in entry_choices or series_group_id in series_choices
                decision = "excluded" if explicit else "awaiting_opt_in"
                excluded += 1
                if decision == "awaiting_opt_in":
                    excluded -= 1
        entry["series_group_id"] = series_group_id
        entry["adoption_decision"] = decision
        entry["adopted"] = decision in {"included_existing", "would_create_missing"}
        planned.append(entry)

    return CBLAdoptionPlan(
        entries=tuple(planned),
        reused_existing_count=reused,
        missing_would_create_count=missing,
        excluded_count=excluded,
        unresolved_count=unresolved,
        final_adopted_count=len(adopted_positions),
        final_adopted_order=tuple(adopted_positions),
    )


async def preview_cbl_adoption(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    series_decisions: dict[str, bool] | None = None,
    entry_decisions: dict[str, bool] | None = None,
) -> tuple[CBLReconciliationReport, CBLAdoptionPlan]:
    """Return reconciliation and a dry-run adoption plan without mutating rows."""
    report = await reconcile_cbl_source_list(db, user_id=user_id, list_id=list_id)
    entries = tuple(
        {**entry, "series_group_id": cbl_series_group_id(entry)} for entry in report.entries
    )
    return report, calculate_cbl_adoption_plan(
        entries,
        series_decisions=series_decisions,
        entry_decisions=entry_decisions,
    )


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
            content_hash=list_row.content_hash,
            revision_sha=list_row.revision_sha,
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

    series_identity_ids = {
        entry.external_series_identity_id
        for entry in entries
        if entry.external_series_identity_id is not None
    }
    series_external_by_id: dict[int, tuple[str, str]] = {}
    if series_identity_ids:
        series_result = await db.execute(
            select(
                ExternalIdentity.id,
                ExternalIdentity.provider,
                ExternalIdentity.external_id,
            ).where(
                ExternalIdentity.id.in_(series_identity_ids),
                ExternalIdentity.entity_type == "series",
            )
        )
        series_external_by_id = {row[0]: (row[1], row[2]) for row in series_result.all()}

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
                "series_provider": (
                    series_external_by_id.get(entry.external_series_identity_id, (None, None))[0]
                    if entry.external_series_identity_id is not None
                    else None
                ),
                "series_external_id": (
                    series_external_by_id.get(entry.external_series_identity_id, (None, None))[1]
                    if entry.external_series_identity_id is not None
                    else None
                ),
                "cbl_entry_id": entry.id,
                "volume_year": entry.volume_year,
                "publication_year": entry.publication_year,
            }
        )

    resolved = await resolve_cbl_entries_to_canonical(db, user_id=user_id, cbl_entries=normalized)

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
            "resolved_via_comicvine_canonical_ambiguous",
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
                "comicvine_series_id": cbl_comicvine_series_id(norm),
                "series_provider": norm.get("series_provider"),
                "series_external_id": norm.get("series_external_id"),
                "external_issue_identity_id": norm.get("external_issue_identity_id"),
                "external_series_identity_id": norm.get("external_series_identity_id"),
                "cbl_entry_id": norm.get("cbl_entry_id"),
                "resolved_issue_id": canon.resolved_issue_id,
                "canonical_issue_id": canon.canonical_issue_id,
                "resolution_status": canon.resolution_status,
                "is_duplicate_identity": canon.is_duplicate_identity,
                "read_status": canon.read_status,
                "read_at": canon.read_at,
            }
        )

    # First unread ordered entry after overlaying actual read history.
    first_unread_position: int | None = None
    first_unread_entry: dict[str, object] | None = None
    for entry in report_entries:
        if entry.get("read_status") == "unread" and entry.get("resolved_issue_id") is not None:
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
            "resolved_via_comicvine_canonical_ambiguous",
        ):
            ambiguous_clean.append(pos)
        elif entry.get("resolved_issue_id") is None:
            missing_clean.append(pos)
        if entry.get("is_duplicate_identity"):
            canonical_id = entry.get("canonical_issue_id") or entry.get("resolved_issue_id")
            if isinstance(canonical_id, int):
                duplicate_identity_issues.add(canonical_id)

    resolved_ids = {
        int(entry["resolved_issue_id"])
        for entry in report_entries
        if entry.get("resolved_issue_id") is not None
    }
    for entry in report_entries:
        if entry.get("is_duplicate_identity") and entry.get("canonical_issue_id") is not None:
            resolved_ids.add(cast(int, entry["canonical_issue_id"]))
    extra = tuple(
        sorted(issue_id for issue_id in baseline_member_issue_ids if issue_id not in resolved_ids)
    )

    first_unread_issue_id = (
        cast(int, first_unread_entry["resolved_issue_id"])
        if first_unread_entry and first_unread_entry.get("resolved_issue_id") is not None
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
        content_hash=list_row.content_hash,
        revision_sha=list_row.revision_sha,
        declared_issue_count=list_row.declared_issue_count,
        missing_source_entries=tuple(sorted(missing_clean)),
        extra_member_issue_ids=extra,
        ambiguous_mappings=tuple(sorted(ambiguous_clean)),
        duplicate_identity_issues=tuple(sorted(duplicate_identity_issues)),
        first_unread_issue_id=first_unread_issue_id,
    )
