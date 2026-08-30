"""CBL reconciliation to canonical physical-issue identity.

Reconciliation resolves every CBL source position to the canonical ComicPile
Issue that represents the same physical comic, preferring ComicVine issue ID
evidence. Thread/position boundaries never define physical identity. Entries
without ComicVine evidence are surfaced as ambiguous rather than silently
skipped or merged via title + issue number.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSourceEntry
from app.services.issue_identity_reconciliation import resolve_cbl_entries_to_canonical


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


async def reconcile_cbl_source_list(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
) -> CBLReconciliationReport:
    """Reconcile one CBL source list to canonical physical-issue identities.

    Uses the canonical resolution helper so CBL entries that carry a ComicVine
    issue ID always resolve to the history-preserving canonical Issue rather
    than whichever duplicate happens to hold the external mapping.

    Args:
        db: Async database session.
        user_id: Owner user ID whose issues are eligible for matching.
        list_id: CBLSourceList identifier to reconcile.

    Returns:
        Structured reconciliation report including the first unread ordered entry
        after overlaying actual read history.
    """
    result = await db.execute(
        select(CBLSourceEntry)
        .where(CBLSourceEntry.list_id == list_id)
        .order_by(CBLSourceEntry.position)
    )
    entries = list(result.scalars().all())
    if not entries:
        return CBLReconciliationReport(
            total_positions=0,
            resolved_count=0,
            unresolved_count=0,
            duplicate_identity_groups=0,
            ambiguous_count=0,
            entries=(),
            first_unread_position=None,
            first_unread_entry=None,
        )

    # Resolve external identity ids to external_id strings where available.
    from app.models.external_identity import ExternalIdentity

    identity_ids = {e.external_issue_identity_id for e in entries if e.external_issue_identity_id is not None}
    external_by_id: dict[int, str] = {}
    if identity_ids:
        id_result = await db.execute(
            select(ExternalIdentity.id, ExternalIdentity.external_id).where(ExternalIdentity.id.in_(identity_ids))
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
        if canon.resolution_status in ("ambiguous_no_comicvine_id", "comicvine_identity_not_known"):
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
        if entry.get("read_status") == "unread" and entry.get("resolved_issue_id") is not None:
            first_unread_position = int(entry["cbl_position"])
            first_unread_entry = entry
            break
        if entry.get("resolved_issue_id") is None:
            # Unresolved entries are not counted as read; they are still gaps.
            # Keep scanning for the true first unread resolved entry.
            continue

    return CBLReconciliationReport(
        total_positions=len(report_entries),
        resolved_count=resolved_count,
        unresolved_count=unresolved_count,
        duplicate_identity_groups=duplicate_groups,
        ambiguous_count=ambiguous_count,
        entries=tuple(report_entries),
        first_unread_position=first_unread_position,
        first_unread_entry=first_unread_entry,
    )
