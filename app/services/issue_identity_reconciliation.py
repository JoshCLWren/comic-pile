"""Canonical physical-issue identity reconciliation for duplicate ComicPile rows.

One physical comic must have one canonical ComicPile identity for read state,
history, ratings, crossover membership, and metadata associations. When a user
owns multiple Issue rows that share the same confirmed ComicVine issue ID they
represent the same physical comic and must not behave as independently readable
copies.

This module provides detection, canonical resolution, reporting, and
history-preserving consolidation without destructive automatic merges. Title +
issue_number alone is never sufficient evidence when provider IDs disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread


@dataclass(frozen=True, slots=True)
class DuplicateIdentityAnomaly:
    """One confirmed ComicVine identity that maps to multiple user-owned issues."""

    comicvine_issue_id: str
    external_identity_id: int
    issue_ids: tuple[int, ...]
    thread_ids: tuple[int, ...]
    statuses: tuple[str, ...]
    has_read: bool
    has_unread: bool
    issue_details: tuple[dict[str, object], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CanonicalResolutionResult:
    """Canonical physical-issue identity resolution for one ComicVine ID."""

    comicvine_issue_id: str
    external_identity_id: int
    canonical_issue_id: int | None
    all_issue_ids: tuple[int, ...]
    is_duplicate: bool
    is_ambiguous: bool
    reason: str


@dataclass(frozen=True, slots=True)
class IdentityConsolidationPreview:
    """Dry-run description of a history-preserving consolidation."""

    comicvine_issue_id: str
    canonical_issue_id: int
    source_issue_ids: tuple[int, ...]
    read_state_to_preserve: bool
    read_at_to_preserve: datetime | None
    events_to_move: int
    ratings_to_preserve: bool
    is_ambiguous: bool
    reason: str


@dataclass(frozen=True, slots=True)
class CBLCanonicalEntry:
    """One CBL source entry resolved to canonical physical-issue identity."""

    cbl_position: int
    cbl_series_name: str
    cbl_issue_number: str
    comicvine_issue_id: str | None
    resolved_issue_id: int | None
    canonical_issue_id: int | None
    resolution_status: str
    is_duplicate_identity: bool
    read_status: str | None
    read_at: datetime | None


@dataclass(frozen=True, slots=True)
class IdentityReport:
    """Machine-readable report of identity anomalies for a user."""

    total_duplicate_groups: int
    total_affected_issues: int
    anomalies: tuple[DuplicateIdentityAnomaly, ...]
    conflicting_provider_ids: tuple[dict[str, object], ...]


_COMICVINE_ISSUE_ENTITY = "issue"
_CONFIRMED_STATUS = "confirmed"


async def find_duplicate_physical_issues(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[DuplicateIdentityAnomaly]:
    """Find confirmed ComicVine identities that map to multiple user-owned issues.

    A duplicate is defined as one ExternalIdentity (comicvine issue) with
    status=confirmed on multiple Issue rows that belong to the same user via
    their threads. Thread boundaries do not define physical identity - two
    threads with issues at the same position/number can still be the same
    physical comic when their ComicVine IDs agree.

    Args:
        db: Async database session.
        user_id: Owner user ID to scope the anomaly search.

    Returns:
        One anomaly per duplicated ComicVine issue identity, each listing all
        affected Issue rows for that user.
    """
    result = await db.execute(
        text(
            """
            SELECT
                ei.external_id AS comicvine_issue_id,
                ei.id AS external_identity_id,
                array_agg(iem.issue_id ORDER BY iem.issue_id) AS issue_ids,
                array_agg(i.thread_id ORDER BY iem.issue_id) AS thread_ids,
                array_agg(i.status ORDER BY iem.issue_id) AS statuses,
                array_agg(i.read_at ORDER BY iem.issue_id) AS read_ats,
                array_agg(i.issue_number ORDER BY iem.issue_id) AS issue_numbers,
                array_agg(t.title ORDER BY iem.issue_id) AS thread_titles
            FROM external_identities ei
            JOIN issue_external_identity_mappings iem
                ON iem.external_identity_id = ei.id
            JOIN issues i ON i.id = iem.issue_id
            JOIN threads t ON t.id = i.thread_id
            WHERE ei.provider = :provider
              AND ei.entity_type = :entity_type
              AND iem.status = :confirmed
              AND t.user_id = :user_id
            GROUP BY ei.id, ei.external_id
            HAVING COUNT(DISTINCT iem.issue_id) > 1
            ORDER BY ei.external_id
            """
        ),
        {
            "provider": "comicvine",
            "entity_type": _COMICVINE_ISSUE_ENTITY,
            "confirmed": _CONFIRMED_STATUS,
            "user_id": user_id,
        },
    )
    anomalies: list[DuplicateIdentityAnomaly] = []
    for row in result.mappings():
        issue_ids = tuple(int(v) for v in (row["issue_ids"] or []))
        thread_ids = tuple(int(v) for v in (row["thread_ids"] or []))
        statuses = tuple(str(v) for v in (row["statuses"] or []))
        has_read = "read" in statuses
        has_unread = "unread" in statuses
        issue_numbers = list(row["issue_numbers"] or [])
        thread_titles = list(row["thread_titles"] or [])
        read_ats = list(row["read_ats"] or [])
        details: list[dict[str, object]] = []
        for idx, iid in enumerate(issue_ids):
            details.append(
                {
                    "issue_id": iid,
                    "thread_id": thread_ids[idx] if idx < len(thread_ids) else None,
                    "thread_title": thread_titles[idx] if idx < len(thread_titles) else None,
                    "issue_number": issue_numbers[idx] if idx < len(issue_numbers) else None,
                    "status": statuses[idx] if idx < len(statuses) else None,
                    "read_at": read_ats[idx] if idx < len(read_ats) else None,
                }
            )
        anomalies.append(
            DuplicateIdentityAnomaly(
                comicvine_issue_id=str(row["comicvine_issue_id"]),
                external_identity_id=int(row["external_identity_id"]),
                issue_ids=issue_ids,
                thread_ids=thread_ids,
                statuses=statuses,
                has_read=has_read,
                has_unread=has_unread,
                issue_details=tuple(details),
            )
        )
    return anomalies


async def find_conflicting_provider_identities(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[dict[str, object]]:
    """Find issues that have confirmed mappings to different ComicVine IDs.

    This surfaces ambiguous cases where the same Issue row claims conflicting
    provider identities (should not happen via normal single-provider confirm
    but may exist from legacy or manual corrections). These are reported
    rather than silently merged.

    Args:
        db: Async database session.
        user_id: Owner user ID.

    Returns:
        One entry per Issue with conflicting confirmed ComicVine IDs.
    """
    result = await db.execute(
        text(
            """
            SELECT
                i.id AS issue_id,
                i.thread_id,
                t.title AS thread_title,
                i.issue_number,
                array_agg(ei.external_id ORDER BY ei.external_id) AS comicvine_ids,
                COUNT(DISTINCT ei.id) AS distinct_identities
            FROM issues i
            JOIN threads t ON t.id = i.thread_id
            JOIN issue_external_identity_mappings iem ON iem.issue_id = i.id
            JOIN external_identities ei ON ei.id = iem.external_identity_id
            WHERE t.user_id = :user_id
              AND ei.provider = :provider
              AND ei.entity_type = :entity_type
              AND iem.status = :confirmed
            GROUP BY i.id, i.thread_id, t.title, i.issue_number
            HAVING COUNT(DISTINCT ei.id) > 1
            ORDER BY i.id
            """
        ),
        {
            "provider": "comicvine",
            "entity_type": _COMICVINE_ISSUE_ENTITY,
            "confirmed": _CONFIRMED_STATUS,
            "user_id": user_id,
        },
    )
    conflicts: list[dict[str, object]] = []
    for row in result.mappings():
        conflicts.append(
            {
                "issue_id": int(row["issue_id"]),
                "thread_id": int(row["thread_id"]),
                "thread_title": str(row["thread_title"] or ""),
                "issue_number": str(row["issue_number"] or ""),
                "comicvine_ids": list(row["comicvine_ids"] or []),
                "distinct_identities": int(row["distinct_identities"]),
            }
        )
    return conflicts


async def resolve_canonical_issue(
    db: AsyncSession,
    *,
    user_id: int,
    comicvine_issue_id: str,
) -> CanonicalResolutionResult:
    """Resolve the single canonical Issue row for a confirmed ComicVine issue ID.

    Canonical selection prefers the Issue that carries factual read/rating/event
    history so reconciliation does not lose it. Title + issue_number agreement
    is never used as identity evidence when ComicVine IDs disagree.

    Selection priority:
    1. Only one user-owned confirmed mapping -> that issue is canonical.
    2. Multiple confirmed mappings -> prefer read over unread, then earliest
       read_at, then lowest issue id. Ambiguous divergence (one read, one unread)
       is still resolved to the read holder but flagged as requires attention.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        comicvine_issue_id: Confirmed ComicVine issue external_id string.

    Returns:
        Canonical resolution including whether the identity is duplicated and
        whether it requires ambiguous-case handling.
    """
    normalized = comicvine_issue_id.strip()
    result = await db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == "comicvine",
            ExternalIdentity.entity_type == _COMICVINE_ISSUE_ENTITY,
            ExternalIdentity.external_id == normalized,
        )
    )
    identity = result.scalar_one_or_none()
    if identity is None:
        return CanonicalResolutionResult(
            comicvine_issue_id=normalized,
            external_identity_id=0,
            canonical_issue_id=None,
            all_issue_ids=(),
            is_duplicate=False,
            is_ambiguous=False,
            reason="no_external_identity",
        )

    mapping_result = await db.execute(
        select(Issue.id, Issue.status, Issue.read_at, Issue.thread_id)
        .join(IssueExternalIdentityMapping, IssueExternalIdentityMapping.issue_id == Issue.id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(
            IssueExternalIdentityMapping.external_identity_id == identity.id,
            IssueExternalIdentityMapping.status == _CONFIRMED_STATUS,
            Thread.user_id == user_id,
        )
        .order_by(Issue.id)
    )
    rows = mapping_result.all()
    if not rows:
        return CanonicalResolutionResult(
            comicvine_issue_id=normalized,
            external_identity_id=identity.id,
            canonical_issue_id=None,
            all_issue_ids=(),
            is_duplicate=False,
            is_ambiguous=False,
            reason="no_owned_issue",
        )
    all_ids = tuple(int(r[0]) for r in rows)
    if len(all_ids) == 1:
        return CanonicalResolutionResult(
            comicvine_issue_id=normalized,
            external_identity_id=identity.id,
            canonical_issue_id=all_ids[0],
            all_issue_ids=all_ids,
            is_duplicate=False,
            is_ambiguous=False,
            reason="single_canonical",
        )

    # Prefer read history holder; never infer from title+number when provider IDs disagree.
    read_rows = [(r[0], r[2]) for r in rows if str(r[1]) == "read"]
    if read_rows:
        # Earliest read_at first, then lowest id. Use max datetime as sentinel for NULL read_at.
        sentinel = datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
        read_rows.sort(key=lambda item: (item[1] if item[1] is not None else sentinel, int(item[0])))
        # If the anomaly spans read and unread for same physical issue, surface as needing review.
        statuses = [str(r[1]) for r in rows]
        is_ambiguous_divergence = "read" in statuses and "unread" in statuses
        return CanonicalResolutionResult(
            comicvine_issue_id=normalized,
            external_identity_id=identity.id,
            canonical_issue_id=int(read_rows[0][0]),
            all_issue_ids=all_ids,
            is_duplicate=True,
            is_ambiguous=is_ambiguous_divergence,
            reason="duplicate_prefers_read_history" if is_ambiguous_divergence else "duplicate_canonical_by_read_history",
        )

    # All unread - canonical is lowest id, still duplicate.
    return CanonicalResolutionResult(
        comicvine_issue_id=normalized,
        external_identity_id=identity.id,
        canonical_issue_id=all_ids[0],
        all_issue_ids=all_ids,
        is_duplicate=True,
        is_ambiguous=False,
        reason="duplicate_all_unread",
    )


async def preview_consolidation(
    db: AsyncSession,
    *,
    user_id: int,
    comicvine_issue_id: str,
    keep_issue_id: int | None = None,
) -> IdentityConsolidationPreview | None:
    """Preview a history-preserving consolidation for one duplicated ComicVine identity.

    No rows are mutated. The preview reports what read state, timestamps, and
    event/rating facts would be preserved when consolidating to the canonical.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        comicvine_issue_id: ComicVine external_id to consolidate.
        keep_issue_id: Explicit canonical issue to keep. When None the
            service-selected canonical is used.

    Returns:
        Consolidation preview or None when no duplicated identity exists.
    """
    resolution = await resolve_canonical_issue(db, user_id=user_id, comicvine_issue_id=comicvine_issue_id)
    if not resolution.is_duplicate or resolution.canonical_issue_id is None:
        return None

    canonical_id = keep_issue_id if keep_issue_id is not None else resolution.canonical_issue_id
    if canonical_id not in resolution.all_issue_ids:
        return IdentityConsolidationPreview(
            comicvine_issue_id=comicvine_issue_id,
            canonical_issue_id=resolution.canonical_issue_id,
            source_issue_ids=resolution.all_issue_ids,
            read_state_to_preserve=False,
            read_at_to_preserve=None,
            events_to_move=0,
            ratings_to_preserve=False,
            is_ambiguous=True,
            reason="keep_issue_not_in_duplicate_set",
        )

    other_ids = tuple(i for i in resolution.all_issue_ids if i != canonical_id)
    canonical_issue = await db.get(Issue, canonical_id)
    if canonical_issue is None:
        return None

    # Collect read state across the group.
    read_state_to_preserve = False
    earliest_read_at: datetime | None = None
    for iid in resolution.all_issue_ids:
        issue = await db.get(Issue, iid)
        if issue is None:
            continue
        if issue.status == "read" and issue.read_at is not None:
            read_state_to_preserve = True
            if earliest_read_at is None or issue.read_at < earliest_read_at:
                earliest_read_at = issue.read_at
        elif issue.status == "read":
            read_state_to_preserve = True

    # Canonical already carries that state? Still reported as preserved.
    has_canonical_read = canonical_issue.status == "read"

    events_to_move = 0
    ratings_to_preserve = False
    if other_ids:
        events_result = await db.execute(
            select(func.count())
            .select_from(Event)
            .where(Event.issue_id.in_(other_ids))
        )
        events_to_move = int(events_result.scalar() or 0)
        ratings_result = await db.execute(
            select(func.count())
            .select_from(Event)
            .where(Event.issue_id.in_(other_ids), Event.rating.is_not(None))
        )
        ratings_to_preserve = bool(ratings_result.scalar())

    return IdentityConsolidationPreview(
        comicvine_issue_id=comicvine_issue_id,
        canonical_issue_id=canonical_id,
        source_issue_ids=other_ids,
        read_state_to_preserve=read_state_to_preserve and not has_canonical_read,
        read_at_to_preserve=earliest_read_at if (read_state_to_preserve and not has_canonical_read) else None,
        events_to_move=events_to_move,
        ratings_to_preserve=ratings_to_preserve,
        is_ambiguous=resolution.is_ambiguous,
        reason=resolution.reason,
    )


async def consolidate_duplicate_issues(
    db: AsyncSession,
    *,
    user_id: int,
    comicvine_issue_id: str,
    keep_issue_id: int | None = None,
) -> IdentityConsolidationPreview | None:
    """Consolidate duplicate Issue rows for one ComicVine identity without losing history.

    Read state, earliest read_at, and event/rating facts from non-canonical
    rows are moved to the canonical row. Non-canonical Issue rows are left in
    place but their read state is cleared so the physical comic has one
    canonical read identity. No Issue rows are deleted so thread segmentation
    remains inspectable.

    Ambiguous cases where title+issue_number agree but ComicVine IDs disagree
    are never auto-merged; those are surfaced via anomaly detection and require
    explicit keep_issue_id.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        comicvine_issue_id: ComicVine external_id to consolidate.
        keep_issue_id: Explicit canonical issue to keep. When None the
            service-selected canonical is used.

    Returns:
        Applied consolidation summary or None when no duplicated identity exists.
    """
    preview = await preview_consolidation(
        db, user_id=user_id, comicvine_issue_id=comicvine_issue_id, keep_issue_id=keep_issue_id
    )
    if preview is None or preview.is_ambiguous and keep_issue_id is None:
        # Ambiguous read/unread divergence requires explicit keeper; surface rather than merge.
        if preview is not None and preview.is_ambiguous:
            return preview
        if preview is None:
            return None

    if preview.is_ambiguous and preview.reason == "keep_issue_not_in_duplicate_set":
        return preview

    canonical = await db.get(Issue, preview.canonical_issue_id)
    if canonical is None:
        return None

    # Preserve read history on canonical.
    if preview.read_state_to_preserve:
        canonical.status = "read"
        if preview.read_at_to_preserve is not None:
            canonical.read_at = preview.read_at_to_preserve

    # Move events/ratings: reassign issue_id to canonical so history is not lost.
    if preview.source_issue_ids:
        for source_id in preview.source_issue_ids:
            source_issue = await db.get(Issue, source_id)
            if source_issue is None:
                continue
            # Reassign events referencing the duplicate to canonical.
            await db.execute(
                text("UPDATE events SET issue_id = :canonical WHERE issue_id = :source"),
                {"canonical": preview.canonical_issue_id, "source": source_id},
            )
            # Clear read state on non-canonical so it no longer behaves as independent.
            if source_issue.status == "read":
                source_issue.status = "unread"
                source_issue.read_at = None

    await db.flush()
    return preview


async def get_identity_report(
    db: AsyncSession,
    *,
    user_id: int,
) -> IdentityReport:
    """Build a focused report of all identity anomalies for a user.

    Args:
        db: Async database session.
        user_id: Owner user ID.

    Returns:
        Structured report with duplicate groups and conflicting provider identities.
    """
    anomalies = await find_duplicate_physical_issues(db, user_id=user_id)
    conflicts = await find_conflicting_provider_identities(db, user_id=user_id)
    total_affected = sum(len(a.issue_ids) for a in anomalies)
    return IdentityReport(
        total_duplicate_groups=len(anomalies),
        total_affected_issues=total_affected,
        anomalies=tuple(anomalies),
        conflicting_provider_ids=tuple(conflicts),
    )


async def resolve_cbl_entries_to_canonical(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_entries: list[dict[str, object]],
) -> list[CBLCanonicalEntry]:
    """Resolve CBL source entries to canonical physical-issue Issue IDs.

    Each entry is expected to carry at minimum:
    - position, series_name, issue_number, comicvine_issue_id (or None)

    When a ComicVine issue ID is available and confirmed on any user-owned
    Issue, the canonical Issue for that physical comic is returned. Title +
    issue_number alone is never treated as identity when ComicVine evidence
    disagrees.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        cbl_entries: Normalized CBL entries with ComicVine mapping.

    Returns:
        One resolved entry per input, with canonical resolution status.
    """
    results: list[CBLCanonicalEntry] = []
    for entry in cbl_entries:
        position = int(entry.get("position") or 0)
        series_name = str(entry.get("series_name") or "")
        issue_number = str(entry.get("issue_number") or "")
        comicvine_issue_id = entry.get("comicvine_issue_id")
        cvid_str = str(comicvine_issue_id).strip() if comicvine_issue_id is not None else None
        if cvid_str == "":
            cvid_str = None

        if cvid_str is not None:
            # Check for conflicting title+number evidence - never merge on title alone.
            resolution = await resolve_canonical_issue(
                db, user_id=user_id, comicvine_issue_id=cvid_str
            )
            if resolution.canonical_issue_id is not None:
                canon_issue = await db.get(Issue, resolution.canonical_issue_id)
                results.append(
                    CBLCanonicalEntry(
                        cbl_position=position,
                        cbl_series_name=series_name,
                        cbl_issue_number=issue_number,
                        comicvine_issue_id=cvid_str,
                        resolved_issue_id=resolution.canonical_issue_id,
                        canonical_issue_id=resolution.canonical_issue_id,
                        resolution_status="resolved_via_comicvine_canonical"
                        if not resolution.is_ambiguous
                        else "resolved_via_comicvine_canonical_ambiguous",
                        is_duplicate_identity=resolution.is_duplicate,
                        read_status=canon_issue.status if canon_issue else None,
                        read_at=canon_issue.read_at if canon_issue else None,
                    )
                )
                continue
            if resolution.reason == "no_owned_issue":
                results.append(
                    CBLCanonicalEntry(
                        cbl_position=position,
                        cbl_series_name=series_name,
                        cbl_issue_number=issue_number,
                        comicvine_issue_id=cvid_str,
                        resolved_issue_id=None,
                        canonical_issue_id=None,
                        resolution_status="no_owned_issue_for_comicvine_id",
                        is_duplicate_identity=False,
                        read_status=None,
                        read_at=None,
                    )
                )
                continue
            # no_external_identity -> ambiguous provider evidence; surface rather than guess.
            results.append(
                CBLCanonicalEntry(
                    cbl_position=position,
                    cbl_series_name=series_name,
                    cbl_issue_number=issue_number,
                    comicvine_issue_id=cvid_str,
                    resolved_issue_id=None,
                    canonical_issue_id=None,
                    resolution_status="comicvine_identity_not_known",
                    is_duplicate_identity=False,
                    read_status=None,
                    read_at=None,
                )
            )
            continue

        # No ComicVine ID on the CBL entry - report ambiguous; do not infer from title+number.
        results.append(
            CBLCanonicalEntry(
                cbl_position=position,
                cbl_series_name=series_name,
                cbl_issue_number=issue_number,
                comicvine_issue_id=None,
                resolved_issue_id=None,
                canonical_issue_id=None,
                resolution_status="ambiguous_no_comicvine_id",
                is_duplicate_identity=False,
                read_status=None,
                read_at=None,
            )
        )
    return results


async def check_hydration_would_duplicate(
    db: AsyncSession,
    *,
    user_id: int,
    comicvine_issue_id: str,
) -> dict[str, object] | None:
    """Check whether creating a new Issue for a ComicVine ID would duplicate an existing physical issue.

    This is called before hydration/import creates a new Issue row. If the
    ComicVine ID already has a confirmed mapping to a user-owned Issue, the
    caller should link to the existing canonical rather than inserting a duplicate.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        comicvine_issue_id: ComicVine external_id that would be assigned.

    Returns:
        Existing canonical info when duplication would occur, else None.
    """
    resolution = await resolve_canonical_issue(db, user_id=user_id, comicvine_issue_id=comicvine_issue_id)
    if resolution.canonical_issue_id is not None:
        return {
            "comicvine_issue_id": comicvine_issue_id,
            "existing_canonical_issue_id": resolution.canonical_issue_id,
            "all_issue_ids": list(resolution.all_issue_ids),
            "is_duplicate": resolution.is_duplicate,
            "reason": "would_duplicate_existing_physical_issue",
        }
    return None
