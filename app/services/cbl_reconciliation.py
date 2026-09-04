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

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.external_identities import link_thread_external_series, upsert_external_identity
from app.services.comicvine_resolution import confirm_comicvine_identity
from app.services.issue_identity_reconciliation import (
    resolve_canonical_issue,
    resolve_cbl_entries_to_canonical,
)
from app.services.issue_tracking import recalculate_thread_issue_tracking_state
from comic_pile.dependencies import refresh_user_blocked_status
from comic_pile.queue import acquire_queue_lock, move_to_front


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


@dataclass(frozen=True, slots=True)
class CBLReviewedSource:
    """Source fingerprint accepted by the reader during preview."""

    source_list_id: int
    source_repository: str
    source_path: str
    content_hash: str
    revision_sha: str


@dataclass(frozen=True, slots=True)
class CBLReviewedEntry:
    """Material preview facts that must still hold when adoption commits."""

    cbl_position: int
    cbl_entry_id: int
    series_group_id: str
    series_provider: str | None
    series_external_id: str | None
    comicvine_series_id: str | None
    adoption_class: str
    adoption_decision: str
    adopted: bool
    comicvine_issue_id: str | None
    resolved_issue_id: int | None
    canonical_issue_id: int | None
    resolution_status: str


@dataclass(frozen=True, slots=True)
class CBLPersistedMembership:
    """One persisted source-position membership."""

    membership_id: int
    issue_id: int
    sequence_order: int


@dataclass(frozen=True, slots=True)
class CBLAdoptionCommitResult:
    """Machine-readable result of one atomic CBL adoption."""

    source: CBLReviewedSource
    group_id: int
    group_name: str
    reused_issue_ids: tuple[int, ...]
    created_issue_ids: tuple[int, ...]
    created_thread_ids: tuple[int, ...]
    excluded_source_positions: tuple[int, ...]
    unresolved_source_positions: tuple[int, ...]
    memberships: tuple[CBLPersistedMembership, ...]
    final_adopted_source_positions: tuple[int, ...]
    blocker_changed_thread_ids: tuple[int, ...]
    idempotent_replay: bool


class CBLAdoptionStaleError(Exception):
    """The persisted source or canonical plan no longer matches the review."""

    def __init__(self, reasons: list[str]) -> None:
        """Initialize with stable machine-readable mismatch reasons."""
        super().__init__("The reviewed CBL adoption plan is stale")
        self.reasons = tuple(reasons)


class CBLAdoptionMaterializationError(Exception):
    """An approved entry cannot be represented safely without guessing."""


CBL_ADOPTION_LOCK_NAMESPACE = 2127001


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


def _reviewed_entry(entry: dict[str, object]) -> CBLReviewedEntry:
    """Extract commit-relevant facts from a freshly calculated plan entry."""
    return CBLReviewedEntry(
        cbl_position=int(entry["cbl_position"]),
        cbl_entry_id=int(entry["cbl_entry_id"]),
        series_group_id=str(entry["series_group_id"]),
        series_provider=(
            str(entry["series_provider"]) if entry.get("series_provider") is not None else None
        ),
        series_external_id=(
            str(entry["series_external_id"])
            if entry.get("series_external_id") is not None
            else None
        ),
        comicvine_series_id=(
            str(entry["comicvine_series_id"])
            if entry.get("comicvine_series_id") is not None
            else None
        ),
        adoption_class=str(entry["adoption_class"]),
        adoption_decision=str(entry["adoption_decision"]),
        adopted=bool(entry["adopted"]),
        comicvine_issue_id=(
            str(entry["comicvine_issue_id"])
            if entry.get("comicvine_issue_id") is not None
            else None
        ),
        resolved_issue_id=cast(int | None, entry.get("resolved_issue_id")),
        canonical_issue_id=cast(int | None, entry.get("canonical_issue_id")),
        resolution_status=str(entry["resolution_status"]),
    )


def _entry_mismatch(
    reviewed: CBLReviewedEntry,
    current: CBLReviewedEntry,
    replay_issue_id: int | None,
) -> bool:
    """Return whether a current entry materially differs from its reviewed facts."""
    if reviewed == current:
        return False
    # An identical replay necessarily changes an imported entry from "missing"
    # to "existing". Permit only that exact convergence, tied to the issue
    # already persisted at the reviewed source position in this source's group.
    return not (
        reviewed.adoption_class == "missing_importable"
        and reviewed.adoption_decision == "would_create_missing"
        and reviewed.adopted
        and current.adoption_class == "existing"
        and current.adoption_decision == "included_existing"
        and current.adopted
        and reviewed.cbl_position == current.cbl_position
        and reviewed.cbl_entry_id == current.cbl_entry_id
        and reviewed.series_group_id == current.series_group_id
        and reviewed.series_provider == current.series_provider
        and reviewed.series_external_id == current.series_external_id
        and reviewed.comicvine_series_id == current.comicvine_series_id
        and reviewed.comicvine_issue_id == current.comicvine_issue_id
        and current.resolved_issue_id == replay_issue_id
        and current.canonical_issue_id == replay_issue_id
    )


def _stable_series_key(entry: dict[str, object]) -> tuple[str, str] | None:
    """Return normalized provider series identity, never a title-derived group."""
    provider = str(entry.get("series_provider") or "").strip().casefold()
    external_id = str(entry.get("series_external_id") or "").strip()
    if not provider or not external_id:
        return None
    return provider, external_id


def _issue_number_key(issue_number: str) -> tuple[int, int, str] | None:
    """Normalize simple provider issue numbers into deterministic run order."""
    match = re.fullmatch(r"\s*(\d+)(?:\.(\d+))?([A-Za-z]*)\s*", issue_number)
    if match is None:
        return None
    fraction = int((match.group(2) or "0").ljust(12, "0")[:12])
    return int(match.group(1)), fraction, match.group(3).casefold()


def _comicvine_numeric_id(value: object) -> int | None:
    """Return the numeric ComicVine issue ID from canonical stored forms."""
    normalized = str(value or "").strip()
    return int(normalized) if normalized.isdigit() else None


def _required_issue_number_key(entry: dict[str, object]) -> tuple[int, int, str]:
    """Return a previously validated issue-number key."""
    key = _issue_number_key(str(entry.get("issue_number") or ""))
    if key is None:
        raise CBLAdoptionMaterializationError("Issue number was not safely orderable")
    return key


async def _confirmed_series_threads(
    db: AsyncSession,
    *,
    user_id: int,
    provider: str,
    external_id: str,
) -> tuple[ExternalIdentity, list[Thread]]:
    """Resolve all owned threads confirmed for one stable external series."""
    identity = await upsert_external_identity(
        db,
        provider=provider,
        entity_type="series",
        external_id=external_id,
    )
    threads = list(
        (
            await db.scalars(
                select(Thread)
                .join(
                    ThreadExternalSeriesMapping,
                    ThreadExternalSeriesMapping.thread_id == Thread.id,
                )
                .where(
                    Thread.user_id == user_id,
                    ThreadExternalSeriesMapping.external_identity_id == identity.id,
                    ThreadExternalSeriesMapping.status == "confirmed",
                )
                .order_by(Thread.id)
                .with_for_update(of=Thread)
            )
        ).all()
    )
    return identity, threads


def _target_from_series_evidence(
    *,
    provider: str,
    external_id: str,
    mapped_threads: list[Thread],
    canonical_thread_ids: set[int],
) -> Thread | None:
    """Return the uniquely proven target, failing on contradictory evidence."""
    mapped_by_id = {thread.id: thread for thread in mapped_threads}
    if not mapped_threads:
        if len(canonical_thread_ids) > 1:
            raise CBLAdoptionMaterializationError(
                f"Canonical issues for {provider}:{external_id} span multiple threads"
            )
        return None
    if len(mapped_threads) == 1:
        mapped = mapped_threads[0]
        if canonical_thread_ids and canonical_thread_ids != {mapped.id}:
            raise CBLAdoptionMaterializationError(
                f"Canonical issue evidence contradicts the confirmed mapping for "
                f"{provider}:{external_id}"
            )
        return mapped
    if len(canonical_thread_ids) != 1:
        raise CBLAdoptionMaterializationError(
            f"External series {provider}:{external_id} maps to multiple owned threads"
        )
    target_id = next(iter(canonical_thread_ids))
    if target_id not in mapped_by_id:
        raise CBLAdoptionMaterializationError(
            f"Canonical issue evidence contradicts confirmed mappings for {provider}:{external_id}"
        )
    return mapped_by_id[target_id]


async def _create_series_thread(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    series_identity: ExternalIdentity,
) -> Thread:
    """Create one empty queued series thread under the queue transaction lock."""
    max_position = await db.scalar(
        select(func.max(Thread.queue_position)).where(Thread.user_id == user_id)
    )
    thread = Thread(
        title=title.strip(),
        format="Comic",
        issues_remaining=0,
        total_issues=0,
        next_unread_issue_id=None,
        reading_progress="not_started",
        queue_position=(max_position or 0) + 1,
        status="active",
        user_id=user_id,
    )
    db.add(thread)
    await db.flush()
    await link_thread_external_series(
        db,
        user_id=user_id,
        thread_id=thread.id,
        external_identity_id=series_identity.id,
        status="confirmed",
        evidence_source="cbl_adoption",
        confidence=1.0,
    )
    return thread


async def _append_missing_issues(
    db: AsyncSession,
    *,
    user_id: int,
    thread: Thread,
    entries: list[dict[str, object]],
) -> list[Issue]:
    """Merge safely ordered missing issues while preserving existing issue facts."""
    was_completed = thread.status == "completed"
    existing = list(
        (
            await db.scalars(
                select(Issue)
                .where(Issue.thread_id == thread.id)
                .order_by(Issue.position, Issue.id)
                .with_for_update()
            )
        ).all()
    )
    keyed_new: list[tuple[tuple[int, int, str], dict[str, object]]] = []
    for entry in entries:
        key = _issue_number_key(str(entry.get("issue_number") or ""))
        if key is None:
            raise CBLAdoptionMaterializationError(
                f"Source position {entry['cbl_position']} has no safely ordered issue number"
            )
        keyed_new.append((key, entry))
    keyed_new.sort(key=lambda item: item[0])
    keyed_existing = [(_issue_number_key(issue.issue_number), issue) for issue in existing]
    if any(key is None for key, _issue in keyed_existing):
        raise CBLAdoptionMaterializationError(
            f"Existing issues in thread {thread.id} are not safely orderable"
        )
    existing_order = [cast(tuple[int, int, str], key) for key, _issue in keyed_existing]
    if any(
        left >= right
        for left, right in zip(existing_order, existing_order[1:], strict=False)
    ):
        raise CBLAdoptionMaterializationError(
            f"Existing issues in thread {thread.id} are not in strict normalized order"
        )
    all_keys = [*existing_order, *(key for key, _entry in keyed_new)]
    if len(set(all_keys)) != len(all_keys):
        raise CBLAdoptionMaterializationError("Series contains duplicate normalized issue numbers")

    await db.execute(text("SET CONSTRAINTS uq_issue_thread_position DEFERRED"))
    next_temporary_position = max((issue.position for issue in existing), default=0)
    created: list[Issue] = []
    for _key, entry in keyed_new:
        next_temporary_position += 1
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(entry["issue_number"]),
            position=next_temporary_position,
            status="unread",
        )
        db.add(issue)
        await db.flush()
        await confirm_comicvine_identity(
            db,
            user_id=user_id,
            issue_id=issue.id,
            comicvine_issue_id=cast(int, _comicvine_numeric_id(entry["comicvine_issue_id"])),
        )
        created.append(issue)
    merged = sorted(
        [
            *((cast(tuple[int, int, str], key), issue) for key, issue in keyed_existing),
            *((key, issue) for (key, _entry), issue in zip(keyed_new, created, strict=True)),
        ],
        key=lambda item: item[0],
    )
    for position, (_key, issue) in enumerate(merged, start=1):
        issue.position = position
    await db.flush()
    recalculate_thread_issue_tracking_state(thread, [issue for _key, issue in merged])
    if was_completed and created:
        await move_to_front(thread.id, user_id, db, commit=False)
    return created


async def commit_cbl_adoption(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    source: CBLReviewedSource,
    reviewed_entries: tuple[CBLReviewedEntry, ...],
    reviewed_final_positions: tuple[int, ...],
    series_decisions: dict[str, bool],
    entry_decisions: dict[str, bool],
) -> CBLAdoptionCommitResult:
    """Atomically materialize one reviewed, source-backed CBL adoption.

    The caller owns the transaction and must commit exactly once after this
    function returns. A same-user CBL lock precedes source and stale-plan
    validation. When materialization can create or reactivate a thread, the
    established queue transaction lock is acquired before target-thread locks
    and queue-position mutation. The source-list row lock serializes same-source
    adoption through canonical import, membership sync, and blocker refresh.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :user_id)"),
        {"namespace": CBL_ADOPTION_LOCK_NAMESPACE, "user_id": user_id},
    )
    locked_source_row = (
        await db.execute(
            select(CBLSourceList, CBLSource)
            .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
            .where(CBLSourceList.id == list_id)
            .with_for_update()
        )
    ).one_or_none()
    locked_list = locked_source_row[0] if locked_source_row is not None else None
    if locked_list is None or not locked_list.active:
        raise CBLAdoptionStaleError(["source_list_unavailable"])

    report, plan = await preview_cbl_adoption(
        db,
        user_id=user_id,
        list_id=list_id,
        series_decisions=series_decisions,
        entry_decisions=entry_decisions,
    )
    current_source = CBLReviewedSource(
        source_list_id=cast(int, report.source_list_id),
        source_repository=cast(str, report.source_repository),
        source_path=cast(str, report.source_path),
        content_hash=cast(str, report.content_hash),
        revision_sha=cast(str, report.revision_sha),
    )
    reasons: list[str] = []
    if list_id != source.source_list_id:
        reasons.append("source_list_id_path_mismatch")
    if current_source != source:
        reasons.append("source_fingerprint_changed")

    group = await db.scalar(
        select(DependencyGroup)
        .where(
            DependencyGroup.user_id == user_id,
            DependencyGroup.cbl_source_list_id == list_id,
        )
        .with_for_update()
    )
    existing_memberships = []
    if group is not None:
        existing_memberships = list(
            (
                await db.scalars(
                    select(DependencyGroupMembership)
                    .where(DependencyGroupMembership.group_id == group.id)
                    .order_by(DependencyGroupMembership.sequence_order)
                    .with_for_update()
                )
            ).all()
        )
    prior_provenance = (
        group.cbl_source_repository,
        group.cbl_source_path,
        group.cbl_content_hash,
        group.cbl_revision_sha,
    ) if group is not None else None
    prior_memberships = tuple(
        (membership.id, membership.issue_id, membership.sequence_order)
        for membership in existing_memberships
    )
    prior_membership_count = len(existing_memberships)
    replay_by_position = {
        membership.sequence_order: membership.issue_id
        for membership in existing_memberships
        if membership.sequence_order is not None and membership.issue_id is not None
    }

    current_entries = tuple(_reviewed_entry(entry) for entry in plan.entries)
    if len(reviewed_entries) != len(current_entries):
        reasons.append("entry_count_changed")
    else:
        for reviewed, current in zip(reviewed_entries, current_entries, strict=True):
            if _entry_mismatch(reviewed, current, replay_by_position.get(reviewed.cbl_position)):
                reasons.append(f"entry_material_facts_changed:{reviewed.cbl_position}")
    if tuple(plan.final_adopted_order) != reviewed_final_positions:
        # A valid replay retains the reviewed selection positions even though
        # imported entries now classify as existing.
        reasons.append("final_source_positions_changed")
    if reasons:
        raise CBLAdoptionStaleError(reasons)

    selected = [entry for entry in plan.entries if entry.get("adopted") is True]
    selected_identity_keys = [
        str(entry.get("comicvine_issue_id") or f"issue:{entry.get('resolved_issue_id')}")
        for entry in selected
    ]
    if len(set(selected_identity_keys)) != len(selected_identity_keys):
        raise CBLAdoptionMaterializationError(
            "Selected CBL positions contain the same physical comic more than once"
        )
    missing_by_series: dict[tuple[str, str], list[dict[str, object]]] = {}
    selected_by_series: dict[tuple[str, str], list[dict[str, object]]] = {}
    for entry in selected:
        stable_key = _stable_series_key(entry)
        if stable_key is not None:
            selected_by_series.setdefault(stable_key, []).append(entry)
        if entry["adoption_class"] == "missing_importable":
            comicvine_id = _comicvine_numeric_id(entry.get("comicvine_issue_id"))
            if comicvine_id is None:
                raise CBLAdoptionMaterializationError(
                    f"Source position {entry['cbl_position']} lacks a usable ComicVine issue ID"
                )
            series_key = _stable_series_key(entry)
            if series_key is None:
                raise CBLAdoptionMaterializationError(
                    f"Source position {entry['cbl_position']} lacks stable external series identity"
                )
            missing_by_series.setdefault(series_key, []).append(entry)

    if missing_by_series:
        await acquire_queue_lock(user_id, db)

    reused_issue_ids: list[int] = []
    created_issue_ids: list[int] = []
    created_thread_ids: list[int] = []
    issue_by_position: dict[int, int] = {}
    for entry in selected:
        position = int(entry["cbl_position"])
        resolved_issue_id = cast(int | None, entry.get("resolved_issue_id"))
        if resolved_issue_id is not None:
            issue_by_position[position] = resolved_issue_id
            reused_issue_ids.append(resolved_issue_id)
    for (provider, external_id), series_entries in missing_by_series.items():
        still_missing: list[dict[str, object]] = []
        canonical_thread_ids = {
            issue.thread_id
            for selected_entry in selected_by_series[(provider, external_id)]
            if (issue_id := issue_by_position.get(int(selected_entry["cbl_position"]))) is not None
            if (issue := await db.get(Issue, issue_id)) is not None
        }
        for entry in series_entries:
            canonical = await resolve_canonical_issue(
                db,
                user_id=user_id,
                comicvine_issue_id=str(entry["comicvine_issue_id"]),
            )
            if canonical.canonical_issue_id is None:
                still_missing.append(entry)
                continue
            canonical_issue = await db.get(Issue, canonical.canonical_issue_id)
            if canonical_issue is None:
                raise CBLAdoptionMaterializationError("Canonical issue disappeared during adoption")
            issue_by_position[int(entry["cbl_position"])] = canonical_issue.id
            reused_issue_ids.append(canonical_issue.id)
            canonical_thread_ids.add(canonical_issue.thread_id)

        series_identity, mapped_threads = await _confirmed_series_threads(
            db,
            user_id=user_id,
            provider=provider,
            external_id=external_id,
        )
        target = _target_from_series_evidence(
            provider=provider,
            external_id=external_id,
            mapped_threads=mapped_threads,
            canonical_thread_ids=canonical_thread_ids,
        )
        if not mapped_threads:
            if len(canonical_thread_ids) == 1:
                target_id = next(iter(canonical_thread_ids))
                target = await db.scalar(
                    select(Thread)
                    .where(Thread.id == target_id, Thread.user_id == user_id)
                    .with_for_update()
                )
                if target is None:
                    raise CBLAdoptionMaterializationError(
                        f"Canonical target for {provider}:{external_id} is unavailable"
                    )
                await link_thread_external_series(
                    db,
                    user_id=user_id,
                    thread_id=target.id,
                    external_identity_id=series_identity.id,
                    status="confirmed",
                    evidence_source="cbl_adoption_canonical_issue",
                    confidence=1.0,
                )

        if not still_missing:
            continue
        if target is None:
            target = await _create_series_thread(
                db,
                user_id=user_id,
                title=str(series_entries[0]["series_name"]),
                series_identity=series_identity,
            )
            created_thread_ids.append(target.id)
        created = await _append_missing_issues(
            db,
            user_id=user_id,
            thread=target,
            entries=still_missing,
        )
        for entry, issue in zip(
            sorted(still_missing, key=_required_issue_number_key),
            created,
            strict=True,
        ):
            issue_by_position[int(entry["cbl_position"])] = issue.id
            created_issue_ids.append(issue.id)

    if group is None:
        group = DependencyGroup(
            user_id=user_id,
            name=f"CBL: {locked_list.name} [{list_id}]"[:120],
            cbl_source_list_id=list_id,
        )
        db.add(group)
        await db.flush()

    group.cbl_source_repository = source.source_repository
    group.cbl_source_path = source.source_path
    group.cbl_content_hash = source.content_hash
    group.cbl_revision_sha = source.revision_sha

    membership_by_issue = {
        membership.issue_id: membership
        for membership in existing_memberships
        if membership.issue_id is not None
    }
    intended_issue_ids = set(issue_by_position.values())
    for membership in existing_memberships:
        if membership.issue_id not in intended_issue_ids:
            await db.delete(membership)
    persisted: list[CBLPersistedMembership] = []
    for position in sorted(issue_by_position):
        issue_id = issue_by_position[position]
        membership = membership_by_issue.get(issue_id)
        if membership is None:
            membership = DependencyGroupMembership(
                group_id=group.id,
                issue_id=issue_id,
                sequence_order=position,
            )
            db.add(membership)
        else:
            membership.sequence_order = position
        await db.flush()
        persisted.append(
            CBLPersistedMembership(
                membership_id=membership.id,
                issue_id=issue_id,
                sequence_order=position,
            )
        )

    blocker_changes = await refresh_user_blocked_status(user_id, db)
    await db.flush()
    excluded_positions = tuple(
        int(entry["cbl_position"])
        for entry in plan.entries
        if entry.get("adoption_decision") in {"excluded", "awaiting_opt_in"}
    )
    unresolved_positions = tuple(
        int(entry["cbl_position"])
        for entry in plan.entries
        if entry.get("adoption_decision") == "unresolved"
    )
    final_memberships = tuple(
        (item.membership_id, item.issue_id, item.sequence_order) for item in persisted
    )
    exact_prior_state = (
        not created_issue_ids
        and not created_thread_ids
        and prior_provenance
        == (
            source.source_repository,
            source.source_path,
            source.content_hash,
            source.revision_sha,
        )
        and prior_memberships == final_memberships
        and prior_membership_count == len(persisted)
        and not blocker_changes
    )
    return CBLAdoptionCommitResult(
        source=source,
        group_id=group.id,
        group_name=group.name,
        reused_issue_ids=tuple(reused_issue_ids),
        created_issue_ids=tuple(created_issue_ids),
        created_thread_ids=tuple(created_thread_ids),
        excluded_source_positions=excluded_positions,
        unresolved_source_positions=unresolved_positions,
        memberships=tuple(persisted),
        final_adopted_source_positions=reviewed_final_positions,
        blocker_changed_thread_ids=tuple(sorted(blocker_changes)),
        idempotent_replay=exact_prior_state,
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
