"""Canonical CBL adoption commit: atomic materialization of reviewed decisions into a Reading Plan.

This module implements the corrective implementation slice for #2127 under #2366.
It commits the exact reviewed CBL adoption preview/decisions from #2126 and
atomically creates/updates the existing canonical Reading Plan (``ContinuityPlan``)
through the shared Reading Plan writer (:mod:`app.services.continuity_plan_writer`).

Do NOT persist reader intent into ``DependencyGroup`` or make
``DependencyGroupMembership.sequence_order`` a runtime authority.

The commit targets one owned Reading Plan and one active CBL source list.
Revalidates the source fingerprint and reviewed entry facts at commit time;
stale preview fails with a structured conflict and no partial writes.

Reuses canonical existing issues. Materializes only explicitly approved
``missing_importable`` issues, using stable external series identity and ComicVine
issue identity; fail closed rather than title-guessing.

Preserves existing issue IDs, read status, ``read_at``, ratings/events/history,
thread identity, existing Reading Plan node IDs, reader overrides, checkpoints,
convergence gates, lanes, name, and ordering mode.

Adds approved source entries to the **same Reading Plan** in reviewed CBL source
order. Existing plan nodes for the same issue are reused, never duplicated.

Persists source provenance on Reading Plan nodes via ``source_cbl_placements``
fields.

CBL source position is provenance/order input only. No legacy ``cbl-order:source:*``
dependencies and no new ``DependencyGroup`` reader-state representation.

Does not silently change ``informational`` to ``strict_sequential``. Existing explicit
Reading Plan semantics remain authoritative.

Transactional and idempotent. Concurrent same-user/same-source adoption must
not duplicate issues or Reading Plan nodes. The durable guarantee is a unique
``(user_id, cbl_source_list_id)`` receipt plus transactional get-or-create:
retries and concurrent workers converge on one plan even when the client never
receives the success response.

Returns the updated Reading Plan plus machine-readable reused/created/excluded/
unresolved source positions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NamedTuple, cast

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_adoption_receipt import CblAdoptionReceipt
from app.models.cbl_reference import CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread
from app.repositories import cbl_adoption_receipt_repository, issue_repository, thread_repository
from app.schemas.continuity_plan import ContinuityPlanNode, PlanOrderingMode
from app.schemas.shared_types import SourceBackedDecision
from app.services.cbl_reconciliation import reconcile_cbl_source_list
from app.services.continuity_plan_labels import issue_step_label
from app.services.issue_insertion import create_issue_in_natural_order
from app.services.issue_tracking import apply_thread_issue_tracking_state
from app.services.continuity_plan_writer import replace_compiled_rules, validate_node_ownership
from app.services.reading_plan_normalization import drop_issue_nodes_from_plan_json
from comic_pile.dependencies import refresh_user_blocked_status


class AdoptionCommitError(Exception):
    """Base class for adoption commit errors."""


class StalePreviewError(AdoptionCommitError):
    """Raised when the reviewed preview fingerprint no longer matches the source."""

    code: str = "stale_preview"


class ConflictingComicVineIdentityError(AdoptionCommitError):
    """Owned issue number is already confirmed as a different ComicVine issue.

    Reconciliation refuses to attach a CBL entry to that issue. Adoption must
    not override that decision by confirming the new id on the same row.
    """


class MaterializedIssue(NamedTuple):
    """An issue reused or inserted for one approved CBL entry."""

    issue: Issue
    created: bool


@dataclass
class AdoptionMergeReport:
    """Machine-readable source-position outcomes from one adoption merge pass."""

    reused_positions: list[int] = field(default_factory=list)
    created_positions: list[int] = field(default_factory=list)
    excluded_positions: list[int] = field(default_factory=list)
    unresolved_positions: list[int] = field(default_factory=list)


@dataclass
class AdoptionCommitResult:
    """Committed Reading Plan plus machine-readable adoption source positions."""

    plan: ContinuityPlan
    reused_positions: list[int] = field(default_factory=list)
    created_positions: list[int] = field(default_factory=list)
    excluded_positions: list[int] = field(default_factory=list)
    unresolved_positions: list[int] = field(default_factory=list)


async def _verify_preview_fingerprint(
    cbl_list: CBLSourceList,
    client_content_hash: str,
    client_revision_sha: str,
) -> None:
    """Verify that the client-provided preview fingerprint still matches the source.

    Args:
        cbl_list: The active CBL source list row being committed.
        client_content_hash: Content hash from the client's preview request.
        client_revision_sha: Revision SHA from the client's preview request.

    Raises:
        StalePreviewError: If the fingerprint or revision does not match.
    """
    if cbl_list.content_hash != client_content_hash:
        raise StalePreviewError(
            f"Source fingerprint mismatch: expected {cbl_list.content_hash}, "
            f"got {client_content_hash}"
        )

    if cbl_list.revision_sha != client_revision_sha:
        raise StalePreviewError(
            f"Revision mismatch: expected {cbl_list.revision_sha}, "
            f"got {client_revision_sha}"
        )


def _placement_list(placements: object) -> list[dict[str, object]]:
    """Normalize raw stored placements JSON into a list of placement dicts.

    Args:
        placements: Stored node placement value (``None``, a single dict, or a list).

    Returns:
        A list of placement dicts; non-dict noise is discarded.
    """
    if isinstance(placements, dict):
        return [cast(dict[str, object], placements)]
    if isinstance(placements, list):
        return [
            cast(dict[str, object], p) for p in placements if isinstance(p, dict)
        ]
    return []


def _has_placement(placements: list[dict[str, object]], source_path: str) -> bool:
    """Return True when a placement already records the given source path.

    Args:
        placements: Normalized placement dicts for one node.
        source_path: CBL source path to match.

    Returns:
        Whether the node already carries provenance for ``source_path``.
    """
    return any(str(p.get("source_path")) == source_path for p in placements)


async def _find_existing_adopted_plan(
    db: AsyncSession,
    user_id: int,
    source_path: str,
) -> ContinuityPlan | None:
    """Find the existing plan that has CBL source provenance from this source list.

    Scans user-owned plans for nodes containing ``source_cbl_placements`` that
    reference the given source path. Legacy fallback for plans adopted before
    unique receipts existed.

    Args:
        db: Database session.
        user_id: User ID for ownership.
        source_path: Source path to match in CBL placements.

    Returns:
        The existing ContinuityPlan if one is found, None otherwise.
    """
    return await cbl_adoption_receipt_repository.find_plan_by_source_path(
        db, user_id=user_id, source_path=source_path
    )


def _request_fingerprint(
    *,
    content_hash: str,
    revision_sha: str,
    entry_decisions: dict[int, SourceBackedDecision],
    series_overrides: dict[int, SourceBackedDecision],
    series_decisions: dict[str, SourceBackedDecision],
) -> str:
    """Return a stable SHA-256 of the source identity plus reviewed decisions.

    Matching fingerprints are true retries (replay the claimed plan). A
    different fingerprint is a changed list or changed include/exclude
    choices and must merge into the same claimed plan instead of creating
    a second one.

    Args:
        content_hash: Current CBL list content hash.
        revision_sha: Current CBL list revision.
        entry_decisions: Per-entry include/exclude map.
        series_overrides: Per-position overrides of series decisions.
        series_decisions: Per-series include/exclude map.

    Returns:
        Hex digest of the canonical request payload.
    """
    payload = {
        "content_hash": content_hash,
        "revision_sha": revision_sha,
        "entry_decisions": [
            [position, decision.value]
            for position, decision in sorted(entry_decisions.items())
        ],
        "series_overrides": [
            [position, decision.value]
            for position, decision in sorted(series_overrides.items())
        ],
        "series_decisions": [
            [name, decision.value]
            for name, decision in sorted(series_decisions.items())
        ],
    }
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _load_adoption_claim(
    db: AsyncSession,
    user_id: int,
    list_id: int,
) -> tuple[CblAdoptionReceipt, ContinuityPlan] | None:
    """Return the unique (user, list) receipt and plan, if any.

    Args:
        db: Database session.
        user_id: Owner user ID.
        list_id: CBL source list ID.

    Returns:
        The receipt plus claimed Reading Plan, or ``None``.
    """
    return await cbl_adoption_receipt_repository.find_adoption_claim(
        db, user_id=user_id, cbl_source_list_id=list_id
    )


async def _replay_matching_claim(
    db: AsyncSession,
    claim: tuple[CblAdoptionReceipt, ContinuityPlan] | None,
    fingerprint: str,
) -> AdoptionCommitResult | None:
    """Return a no-write replay when the receipt already records this request.

    Args:
        db: Database session.
        claim: Unique receipt and plan, if this user already claimed the list.
        fingerprint: Fingerprint of the current adoption request.

    Returns:
        The existing plan as a commit result, or ``None`` when the caller
        must merge (no receipt, or a different request).
    """
    if claim is None:
        return None
    receipt, plan = claim
    if receipt.request_fingerprint != fingerprint:
        return None
    replay = _result_from_existing_plan(plan)
    await db.commit()
    await db.refresh(replay.plan)
    return replay


def _result_from_existing_plan(plan: ContinuityPlan) -> AdoptionCommitResult:
    """Build a commit result that replays an already-adopted plan without writes.

    Args:
        plan: The uniquely claimed Reading Plan.

    Returns:
        Positions already on the plan as reused, with no created issues.
    """
    reused: list[int] = []
    for node in plan.nodes_json or []:
        for placement in _placement_list(node.get("source_cbl_placements")):
            position = placement.get("position")
            if isinstance(position, int):
                reused.append(position)
    return AdoptionCommitResult(
        plan=plan,
        reused_positions=reused,
        created_positions=[],
        excluded_positions=[],
        unresolved_positions=[],
    )


async def _try_insert_receipt(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    plan_id: int,
    request_fingerprint: str,
) -> CblAdoptionReceipt | None:
    """Record a receipt for a legacy plan; ignore a concurrent unique winner.

    Args:
        db: Database session.
        user_id: Owner user ID.
        list_id: CBL source list ID.
        plan_id: Existing Reading Plan ID.
        request_fingerprint: SHA-256 of the source hash, revision, and decisions.

    Returns:
        The inserted receipt, or ``None`` when a concurrent worker already claimed
        the list.
    """
    try:
        async with db.begin_nested():
            return await cbl_adoption_receipt_repository.insert_adoption_receipt(
                db,
                user_id=user_id,
                cbl_source_list_id=list_id,
                plan_id=plan_id,
                request_fingerprint=request_fingerprint,
            )
    except IntegrityError:
        return None


async def _create_plan_with_receipt(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_list: CBLSourceList,
    request_fingerprint: str,
) -> tuple[ContinuityPlan, bool, CblAdoptionReceipt | None]:
    """Create a Reading Plan and uniquely claim this CBL list, or load the winner.

    Args:
        db: Database session.
        user_id: Owner user ID.
        cbl_list: Active CBL source list being adopted.
        request_fingerprint: SHA-256 of the source hash, revision, and decisions.

    Returns:
        The plan to merge into, whether this caller created it, and the receipt
        when the unique claim is visible.
    """
    source_path = cbl_list.source_path
    try:
        async with db.begin_nested():
            plan = ContinuityPlan(
                user_id=user_id,
                name=cbl_list.name or f"CBL adoption for {source_path}",
                ordering_mode="informational",
                lanes_json=_default_lane(),
                nodes_json=[],
            )
            db.add(plan)
            await db.flush()
            receipt = await cbl_adoption_receipt_repository.insert_adoption_receipt(
                db,
                user_id=user_id,
                cbl_source_list_id=cbl_list.id,
                plan_id=plan.id,
                request_fingerprint=request_fingerprint,
            )
        return plan, True, receipt
    except IntegrityError:
        winner = await _load_adoption_claim(db, user_id, cbl_list.id)
        if winner is None:
            raise AdoptionCommitError(
                "Could not claim this reading order because another adoption "
                "for the same list is already in progress."
            ) from None
        receipt, plan = winner
        return plan, False, receipt


def _comicvine_issue_id(fact: dict[str, object]) -> str | None:
    """Return the ComicVine issue id from one reconciliation fact when present.

    Args:
        fact: Reconciliation facts for one CBL entry.

    Returns:
        The non-empty ComicVine issue id string, or None.
    """
    value = fact.get("comicvine_issue_id")
    if value is None:
        return None
    comicvine_id = str(value).strip()
    return comicvine_id or None


async def _confirm_comicvine_issue_mapping(
    db: AsyncSession,
    issue: Issue,
    comicvine_issue_id: str,
) -> None:
    """Confirm the ComicVine issue identity on an owned issue if it is missing.

    Args:
        db: Database session.
        issue: Owned issue to link.
        comicvine_issue_id: ComicVine issue external id.
    """
    identity_result = await db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == "comicvine",
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.external_id == comicvine_issue_id,
        )
    )
    identity = identity_result.scalar_one_or_none()
    if identity is None:
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=comicvine_issue_id,
            metadata_json={},
        )
        db.add(identity)
        await db.flush()
    existing_mapping = (
        await db.execute(
            select(IssueExternalIdentityMapping.id).where(
                IssueExternalIdentityMapping.issue_id == issue.id,
                IssueExternalIdentityMapping.external_identity_id == identity.id,
            )
        )
    ).scalar_one_or_none()
    if existing_mapping is not None:
        return
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            evidence_source="cbl_adoption_commit",
        )
    )
    await db.flush()


async def _confirmed_comicvine_issue_ids(db: AsyncSession, issue_id: int) -> set[str]:
    """Return ComicVine issue ids already confirmed on one owned issue."""
    result = await db.execute(
        select(ExternalIdentity.external_id)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
        )
        .where(
            IssueExternalIdentityMapping.issue_id == issue_id,
            IssueExternalIdentityMapping.status == "confirmed",
            ExternalIdentity.provider == "comicvine",
            ExternalIdentity.entity_type == "issue",
        )
    )
    return {str(external_id) for external_id in result.scalars().all()}


async def _ensure_missing_issue_created(
    db: AsyncSession,
    user_id: int,
    *,
    fact: dict[str, object],
    volume_year: int | None,
) -> MaterializedIssue:
    """Materialize a missing issue for an explicitly approved CBL entry.

    Reuses a just-created or already-owned issue when the same ComicVine
    identity or the same thread+number is listed more than once in one
    source (#3364). Creates the owning series Thread and the Issue only
    when neither reuse path applies, and links the known ComicVine issue
    identity so the issue is canonical on the next reconciliation. The
    Thread is resolved through the stable external series identity when
    available; a titled series fallback is disambiguated by volume year
    rather than guessed.

    A thread+number match is refused when that issue is already confirmed
    as a different ComicVine issue. Reconciliation rejects that candidate
    for the same reason; adoption must not confirm the conflicting id.

    Args:
        db: Database session.
        user_id: User ID for ownership.
        fact: Reconciliation facts for the CBL entry.
        volume_year: Volume year used to disambiguate the series thread title.

    Returns:
        The reused or newly created issue, and whether a row was inserted.

    Raises:
        ConflictingComicVineIdentityError: The number is already a different comic.
        AdoptionCommitError: If the entry cannot be materialized safely.
    """
    series_name = str(fact.get("series_name") or "")
    issue_number = str(fact.get("issue_number") or "")
    comicvine_id = _comicvine_issue_id(fact)
    external_series_identity_id = fact.get("external_series_identity_id")

    if comicvine_id is not None:
        existing = await issue_repository.find_owned_issue_by_confirmed_identity(
            db,
            user_id,
            provider="comicvine",
            external_id=comicvine_id,
        )
        if existing is not None:
            return MaterializedIssue(existing, False)

    thread = await _find_or_create_series_thread(
        db,
        user_id,
        series_name=series_name,
        external_series_identity_id=(
            int(external_series_identity_id)
            if isinstance(external_series_identity_id, int)
            else None
        ),
        volume_year=volume_year,
    )

    if thread.queue_position < 1:
        thread.queue_position = await thread_repository.max_queue_position(db, user_id) + 1

    existing_issues = await issue_repository.locked_issues(db, thread.id)
    existing_by_number = next(
        (item for item in existing_issues if item.issue_number == issue_number),
        None,
    )
    if existing_by_number is not None:
        confirmed_ids = await _confirmed_comicvine_issue_ids(db, existing_by_number.id)
        if comicvine_id is None:
            if confirmed_ids:
                raise ConflictingComicVineIdentityError(
                    f"{series_name} #{issue_number} is already confirmed as a different "
                    "ComicVine issue, so this entry was left unresolved."
                )
        elif comicvine_id not in confirmed_ids and confirmed_ids:
            raise ConflictingComicVineIdentityError(
                f"{series_name} #{issue_number} is already confirmed as ComicVine "
                f"{', '.join(sorted(confirmed_ids))}, not {comicvine_id}, so this "
                "entry was left unresolved."
            )
        elif comicvine_id not in confirmed_ids:
            await _confirm_comicvine_issue_mapping(db, existing_by_number, comicvine_id)
        return MaterializedIssue(existing_by_number, False)

    try:
        async with db.begin_nested():
            issue = await create_issue_in_natural_order(db, thread.id, issue_number)
    except IntegrityError as exc:
        existing = await issue_repository.find_in_thread_by_number(db, thread.id, issue_number)
        if existing is None:
            raise AdoptionCommitError(
                f"Could not add {series_name} #{issue_number} to the library; "
                "it collides with an issue that is already owned."
            ) from exc
        if comicvine_id is not None:
            await _confirm_comicvine_issue_mapping(db, existing, comicvine_id)
        return MaterializedIssue(existing, False)

    tracked_issues = await issue_repository.get_issues_by_thread(db, thread.id)
    apply_thread_issue_tracking_state(thread, tracked_issues)
    thread.status = "active"

    if comicvine_id is not None:
        await _confirm_comicvine_issue_mapping(db, issue, comicvine_id)

    return MaterializedIssue(issue, True)


async def _find_or_create_series_thread(
    db: AsyncSession,
    user_id: int,
    *,
    series_name: str,
    external_series_identity_id: int | None,
    volume_year: int | None,
) -> Thread:
    """Find or create the series thread backing one materialized issue.

    Prefers the stable external series identity via its thread mapping; falls
    back to a volume-disambiguated ``CBL:` title when identity is unavailable.

    Args:
        db: Database session.
        user_id: User ID for ownership.
        series_name: Series name from CBL.
        external_series_identity_id: External series identity row id if known.
        volume_year: Volume year used to disambiguate the fallback title.

    Returns:
        The owned series Thread.
    """
    if external_series_identity_id is not None:
        thread_result = await db.execute(
            select(Thread)
            .join(ThreadExternalSeriesMapping, ThreadExternalSeriesMapping.thread_id == Thread.id)
            .where(
                Thread.user_id == user_id,
                ThreadExternalSeriesMapping.external_identity_id
                == external_series_identity_id,
            )
        )
        thread = thread_result.scalars().first()
        if thread is not None:
            return thread

        identity = await db.get(ExternalIdentity, external_series_identity_id)
        if identity is not None:
            thread = Thread(
                user_id=user_id,
                title=f"CBL: {series_name}",
                format="comic",
                queue_position=await thread_repository.max_queue_position(db, user_id) + 1,
                status="active",
                reading_progress="not_started",
                created_at=datetime.now(UTC),
            )
            db.add(thread)
            await db.flush()
            db.add(
                ThreadExternalSeriesMapping(
                    thread_id=thread.id,
                    external_identity_id=identity.id,
                    status="confirmed",
                    evidence_source="cbl_adoption_commit",
                )
            )
            await db.flush()
            return thread

    title = f"CBL: {series_name}"
    if volume_year is not None:
        title = f"{title} ({volume_year})"
    thread_result = await db.execute(
        select(Thread).where(
            Thread.user_id == user_id,
            Thread.title == title,
        )
    )
    thread = thread_result.scalar_one_or_none()
    if thread is not None:
        return thread

    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=await thread_repository.max_queue_position(db, user_id) + 1,
        status="active",
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


def _resolve_decision(
    entry: CBLSourceEntry,
    entry_decisions: dict[int, SourceBackedDecision],
    series_overrides: dict[int, SourceBackedDecision],
    series_decisions: dict[str, SourceBackedDecision],
) -> SourceBackedDecision | None:
    """Resolve the effective decision for one CBL source entry.

    An explicit per-position override wins, then the per-position decision, then
    the series-level decision for the entry's series name; otherwise None
    (preserve the default).

    Args:
        entry: CBL source entry.
        entry_decisions: Per-CBL-position decisions.
        series_overrides: Per-CBL-position overrides of series decisions.
        series_decisions: Per-series-name decisions.

    Returns:
        The effective decision, or None when none was provided.
    """
    override = series_overrides.get(entry.position)
    if override is not None:
        return override
    position_decision = entry_decisions.get(entry.position)
    if position_decision is not None:
        return position_decision
    return series_decisions.get(entry.series_name)


def _default_lane() -> list[dict[str, object]]:
    """Return the canonical default lane JSON for adoption plans.

    Returns:
        One default lane dict.
    """
    return [{"id": "default", "name": "Default", "order": 0}]


def _step_label(entry: CBLSourceEntry, fact: dict[str, object]) -> str:
    """Return the planner label for one adopted CBL entry.

    Args:
        entry: CBL source entry.
        fact: Reconciliation facts for the entry.

    Returns:
        ``Series #N`` from CBL series name and issue number.
    """
    series_name = str(fact.get("series_name") or entry.series_name or "")
    issue_number = str(fact.get("issue_number") or getattr(entry, "issue_number", "") or "")
    return issue_step_label(series_name, issue_number)


def _record_node_provenance(
    node: dict[str, object],
    *,
    source_path: str,
    placement: dict[str, object],
    label: str,
) -> None:
    """Attach CBL provenance and a display label to one plan node.

    Args:
        node: Mutable plan node dict.
        source_path: CBL source path for this adoption.
        placement: Placement dict for ``source_cbl_placements``.
        label: Series + issue display label.
    """
    placements = _placement_list(node.get("source_cbl_placements"))
    if not _has_placement(placements, source_path):
        placements.append(placement)
        node["source_cbl_placements"] = placements
    stored_paths = node.get("source_paths")
    paths = (
        [str(path) for path in stored_paths if isinstance(path, str)]
        if isinstance(stored_paths, list | tuple)
        else []
    )
    if source_path not in paths:
        paths.append(source_path)
    node["source_paths"] = paths
    if not str(node.get("label") or "").strip():
        node["label"] = label


def _node_ref_id(node: dict[str, object]) -> int | None:
    """Return the issue ref id of an issue-type plan node when available.

    Args:
        node: One stored plan node dict.

    Returns:
        The integer ``ref_id`` for issue nodes, else None.
    """
    if str(node.get("node_type")) != "issue":
        return None
    ref_id = node.get("ref_id")
    return int(ref_id) if isinstance(ref_id, int) else None


async def _merge_adopted_nodes(
    db: AsyncSession,
    plan: ContinuityPlan,
    user_id: int,
    entries: list[CBLSourceEntry],
    facts_by_entry_id: dict[int, dict[str, object]],
    source_path: str,
    entry_decisions: dict[int, SourceBackedDecision],
    series_overrides: dict[int, SourceBackedDecision],
    series_decisions: dict[str, SourceBackedDecision],
    *,
    new_node_lane_id: str = "default",
) -> AdoptionMergeReport:
    """Merge approved source entries into the plan node set in CBL order.

    Existing plan nodes for the same issue are reused (never duplicated) and
    receive the new ``source_cbl_placements`` provenance. Existing issue nodes
    without a decision are preserved by default. An explicit EXCLUDE removes
    already-present nodes for those issues from the plan record so membership
    and source order cannot keep leftovers the reader just dropped. Missing
    importable entries are materialized only when explicitly approved;
    unresolved/ambiguous entries are never guessed.

    Returns:
        The machine-readable reused/created/excluded/unresolved source positions
        for this merge pass.
    """
    existing_nodes = list(plan.nodes_json or [])
    nodes_by_id = {str(node.get("id")): node for node in existing_nodes}
    issues_by_id: dict[int, dict[str, object]] = {}
    for node in existing_nodes:
        ref_id = _node_ref_id(node)
        if ref_id is not None:
            issues_by_id.setdefault(ref_id, node)

    next_position = 0
    positions = [
        int(node["position"])
        for node in existing_nodes
        if isinstance(node.get("position"), int)
    ]
    if positions:
        next_position = max(positions) + 1

    reused_positions: list[int] = []
    created_positions: list[int] = []
    excluded_positions: list[int] = []
    unresolved_positions: list[int] = []
    excluded_issue_ids: set[int] = set()
    excluded_node_ids: set[str] = set()

    for entry in entries:
        fact = facts_by_entry_id.get(entry.id)

        # An explicit exclusion is honored and reported as excluded even for
        # unresolvable entries: the reader's skip decision stands and the
        # commit report must reflect it, matching the preview.
        early_decision = _resolve_decision(
            entry,
            entry_decisions,
            series_overrides,
            series_decisions,
        )
        if early_decision == SourceBackedDecision.EXCLUDE:
            excluded_positions.append(entry.position)
            excluded_node_ids.add(f"cbl-{entry.id}")
            if fact is not None:
                resolved_issue_id = fact.get("resolved_issue_id")
                if isinstance(resolved_issue_id, int) and not isinstance(
                    resolved_issue_id, bool
                ):
                    excluded_issue_ids.add(resolved_issue_id)
            continue

        if fact is None:
            unresolved_positions.append(entry.position)
            continue

        resolution_status = str(fact.get("resolution_status") or "")
        resolved_issue_id = fact.get("resolved_issue_id")
        existing_issue_id = (
            int(resolved_issue_id) if isinstance(resolved_issue_id, int) else None
        )
        importable = resolution_status == "no_owned_issue_for_comicvine_id"

        if existing_issue_id is None and not importable:
            unresolved_positions.append(entry.position)
            continue

        # #2128 one-decision contract: safely importable missing entries
        # default to included, matching the preview. Only an explicit
        # EXCLUDE (or an unresolvable identity, handled above) keeps an
        # entry out of the committed plan.

        created_now = False
        if existing_issue_id is None:
            try:
                materialized = await _ensure_missing_issue_created(
                    db,
                    user_id,
                    fact=fact,
                    volume_year=entry.volume_year,
                )
            except ConflictingComicVineIdentityError:
                unresolved_positions.append(entry.position)
                continue
            issue, created = materialized
            existing_issue_id = issue.id
            if created:
                created_positions.append(entry.position)
                created_now = True

        node = issues_by_id.get(existing_issue_id)
        if node is None:
            node = nodes_by_id.get(f"cbl-{entry.id}")

        placement: dict[str, object] = {
            "source_path": source_path,
            "position": entry.position,
        }
        label = _step_label(entry, fact)
        if node is not None:
            _record_node_provenance(
                node, source_path=source_path, placement=placement, label=label
            )
            issues_by_id.setdefault(existing_issue_id, node)
            if not created_now:
                reused_positions.append(entry.position)
            continue

        new_node: dict[str, object] = {
            "id": f"cbl-{entry.id}",
            "node_type": "issue",
            "ref_id": existing_issue_id,
            "lane_id": new_node_lane_id,
            "position": next_position,
            "is_checkpoint": False,
            "convergence_gate": [],
            "label": label,
            "source_paths": [source_path],
            "source_cbl_placements": [placement],
        }
        existing_nodes.append(new_node)
        issues_by_id[existing_issue_id] = new_node
        nodes_by_id[str(new_node["id"])] = new_node
        next_position += 1
        if not created_now:
            reused_positions.append(entry.position)

    existing_nodes = drop_issue_nodes_from_plan_json(
        existing_nodes,
        drop_issue_ids=excluded_issue_ids,
        drop_node_ids=excluded_node_ids,
        drop_source_path=source_path,
        drop_source_positions=excluded_positions,
    )
    plan.lanes_json = plan.lanes_json or _default_lane()
    plan.nodes_json = existing_nodes
    return AdoptionMergeReport(
        reused_positions=reused_positions,
        created_positions=created_positions,
        excluded_positions=excluded_positions,
        unresolved_positions=unresolved_positions,
    )


def _plan_ordering_mode(plan: ContinuityPlan) -> PlanOrderingMode:
    """Return the persisted ordering mode validated against the schema literal.

    Args:
        plan: The in-memory plan.

    Returns:
        The plan's ordering mode, validated as a literal.
    """
    return cast(PlanOrderingMode, plan.ordering_mode)


def _to_node_models(nodes: list[dict[str, object]]) -> list[ContinuityPlanNode]:
    """Convert stored node JSON into validated ContinuityPlanNode models.

    Args:
        nodes: Stored plan node dicts.

    Returns:
        The same nodes as validated Pydantic models.
    """
    return [ContinuityPlanNode(**node) for node in nodes]


async def adopt_cbl_material_into_reading_plan(
    db: AsyncSession,
    user_id: int,
    list_id: int,
    entry_decisions: dict[int, SourceBackedDecision],
    series_decisions: dict[str, SourceBackedDecision],
    *,
    series_overrides: dict[int, SourceBackedDecision] | None = None,
    client_content_hash: str | None = None,
    client_revision_sha: str | None = None,
) -> AdoptionCommitResult:
    """Atomically commit reviewed CBL adoption material into a Reading Plan.

    Revalidates the source fingerprint and reconciliation facts, then merges the
    approved source entries into the existing adoption plan (or a new plan) and
    persists via the canonical Reading Plan writer.

    Args:
        db: Database session.
        user_id: User ID for ownership.
        list_id: CBL source list ID.
        entry_decisions: Per-CBL-position decisions.
        series_decisions: Per-series-name decisions.
        series_overrides: Per-CBL-position overrides of series decisions.
        client_content_hash: Content hash from the client's preview request.
        client_revision_sha: Revision SHA from the client's preview request.

    Returns:
        The committed plan plus machine-readable reused/created/excluded/
        unresolved source positions.

    Raises:
        StalePreviewError: If the preview fingerprint has changed.
        AdoptionCommitError: For other adoption failures.
    """
    effective_overrides: dict[int, SourceBackedDecision] = series_overrides or {}
    result = await db.execute(
        select(CBLSourceList).where(CBLSourceList.id == list_id)
    )
    cbl_list = result.scalar_one_or_none()

    if cbl_list is None:
        raise AdoptionCommitError("CBL source list not found")
    if not cbl_list.active:
        raise AdoptionCommitError("CBL source list is not active")

    source_path = cbl_list.source_path

    if client_content_hash is not None or client_revision_sha is not None:
        await _verify_preview_fingerprint(
            cbl_list,
            client_content_hash or "",
            client_revision_sha or "",
        )

    report = await reconcile_cbl_source_list(db, list_id=list_id, user_id=user_id)
    facts_by_entry_id: dict[int, dict[str, object]] = {}
    for entry in report.entries:
        entry_id = entry.get("cbl_entry_id")
        if isinstance(entry_id, int):
            facts_by_entry_id[entry_id] = entry

    entries_result = await db.execute(
        select(CBLSourceEntry)
        .where(CBLSourceEntry.list_id == list_id)
        .order_by(CBLSourceEntry.position)
    )
    entries = list(entries_result.scalars().all())

    fingerprint = _request_fingerprint(
        content_hash=cbl_list.content_hash,
        revision_sha=cbl_list.revision_sha,
        entry_decisions=entry_decisions,
        series_overrides=effective_overrides,
        series_decisions=series_decisions,
    )
    claim = await _load_adoption_claim(db, user_id, list_id)
    replay = await _replay_matching_claim(db, claim, fingerprint)
    if replay is not None:
        return replay

    receipt: CblAdoptionReceipt | None = None
    plan: ContinuityPlan | None = None
    if claim is not None:
        receipt, plan = claim
    else:
        existing_plan = await _find_existing_adopted_plan(db, user_id, source_path)
        if existing_plan is None:
            plan, claimed, receipt = await _create_plan_with_receipt(
                db,
                user_id=user_id,
                cbl_list=cbl_list,
                request_fingerprint=fingerprint,
            )
            if not claimed:
                replay = await _replay_matching_claim(
                    db,
                    None if receipt is None else (receipt, plan),
                    fingerprint,
                )
                if replay is not None:
                    return replay
        else:
            plan = existing_plan
            if plan.id is not None:
                receipt = await _try_insert_receipt(
                    db,
                    user_id=user_id,
                    list_id=list_id,
                    plan_id=plan.id,
                    request_fingerprint=fingerprint,
                )
                if receipt is None:
                    raced = await _load_adoption_claim(db, user_id, list_id)
                    replay = await _replay_matching_claim(db, raced, fingerprint)
                    if replay is not None:
                        return replay
                    if raced is not None:
                        receipt, plan = raced

    if plan is None:
        raise AdoptionCommitError(
            "Could not claim this reading order because another adoption "
            "for the same list is already in progress."
        )

    merge_report = await _merge_adopted_nodes(
        db,
        plan,
        user_id,
        entries,
        facts_by_entry_id,
        source_path,
        entry_decisions,
        effective_overrides,
        series_decisions,
    )

    try:
        node_models = _to_node_models(plan.nodes_json)
    except ValidationError as exc:
        raise AdoptionCommitError(
            "Adopted entries could not be assembled into a valid Reading Plan."
        ) from exc
    await validate_node_ownership(db, user_id=user_id, nodes=node_models)
    try:
        await replace_compiled_rules(
            db,
            user_id=user_id,
            plan=plan,
            nodes=node_models,
            ordering_mode=_plan_ordering_mode(plan),
        )
        if receipt is not None and receipt.request_fingerprint != fingerprint:
            await cbl_adoption_receipt_repository.update_receipt_fingerprint(
                db, receipt, fingerprint
            )
        await refresh_user_blocked_status(user_id, db)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        winner = await _load_adoption_claim(db, user_id, list_id)
        if winner is not None:
            return _result_from_existing_plan(winner[1])
        raise AdoptionCommitError(
            "Could not commit this reading order because it would duplicate "
            "an issue already in the library or plan."
        ) from exc
    except Exception:
        await db.rollback()
        raise

    await db.refresh(plan)
    return AdoptionCommitResult(
        plan=plan,
        reused_positions=merge_report.reused_positions,
        created_positions=merge_report.created_positions,
        excluded_positions=merge_report.excluded_positions,
        unresolved_positions=merge_report.unresolved_positions,
    )