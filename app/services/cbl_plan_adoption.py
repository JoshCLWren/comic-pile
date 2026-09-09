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
not duplicate issues or Reading Plan nodes.

Returns the updated Reading Plan plus machine-readable reused/created/excluded/
unresolved source positions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread
from app.repositories import issue_repository, thread_repository
from app.schemas.continuity_plan import ContinuityPlanNode, PlanOrderingMode
from app.schemas.shared_types import SourceBackedDecision
from app.services.cbl_reconciliation import reconcile_cbl_source_list
from app.services.continuity_plan_writer import replace_compiled_rules, validate_node_ownership


class AdoptionCommitError(Exception):
    """Base class for adoption commit errors."""


class StalePreviewError(AdoptionCommitError):
    """Raised when the reviewed preview fingerprint no longer matches the source."""

    code: str = "stale_preview"


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
    reference the given source path.

    Args:
        db: Database session.
        user_id: User ID for ownership.
        source_path: Source path to match in CBL placements.

    Returns:
        The existing ContinuityPlan if one is found, None otherwise.
    """
    result = await db.execute(
        select(ContinuityPlan).where(ContinuityPlan.user_id == user_id)
    )
    plans = result.scalars().all()

    for plan in plans:
        for node in plan.nodes_json or []:
            placements = _placement_list(node.get("source_cbl_placements"))
            if not placements:
                placements = _placement_list(node.get("source_cbl_placement"))
            if any(str(p.get("source_path")) == source_path for p in placements):
                return plan
    return None


async def _ensure_missing_issue_created(
    db: AsyncSession,
    user_id: int,
    *,
    fact: dict[str, object],
    volume_year: int | None,
) -> Issue:
    """Materialize a missing issue for an explicitly approved CBL entry.

    Creates the owning series Thread and the Issue itself, and links the known
    ComicVine issue identity so the new issue is canonical on the next
    reconciliation. The Thread is resolved through the stable external series
    identity when available; a titled series fallback is disambiguated by volume
    year rather than guessed.

    Args:
        db: Database session.
        user_id: User ID for ownership.
        fact: Reconciliation facts for the CBL entry.
        volume_year: Volume year used to disambiguate the series thread title.

    Returns:
        The newly created Issue.

    Raises:
        AdoptionCommitError: If the entry cannot be materialized safely.
    """
    series_name = str(fact.get("series_name") or "")
    issue_number = str(fact.get("issue_number") or "")
    comicvine_issue_id = fact.get("comicvine_issue_id")
    external_series_identity_id = fact.get("external_series_identity_id")

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
    issue_position = max((item.position for item in existing_issues), default=0) + 1
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=issue_position,
        status="unread",
    )
    db.add(issue)
    await db.flush()

    issues = [*existing_issues, issue]
    unread_issues = [item for item in issues if item.status != "read"]
    thread.total_issues = len(issues)
    thread.issues_remaining = len(unread_issues)
    thread.next_unread_issue_id = min(
        unread_issues,
        key=lambda item: (item.position, item.id),
    ).id
    thread.reading_progress = (
        "not_started" if len(unread_issues) == len(issues) else "in_progress"
    )
    thread.status = "active"

    if comicvine_issue_id is not None:
        identity_result = await db.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "issue",
                ExternalIdentity.external_id == str(comicvine_issue_id),
            )
        )
        identity = identity_result.scalar_one_or_none()
        if identity is None:
            identity = ExternalIdentity(
                provider="comicvine",
                entity_type="issue",
                external_id=str(comicvine_issue_id),
                metadata_json={},
            )
            db.add(identity)
            await db.flush()
        db.add(
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
                evidence_source="cbl_adoption_commit",
            )
        )
        await db.flush()

    return issue


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
    without a decision are preserved by default; missing/importable entries are
    materialized only when explicitly approved; unresolved/ambiguous entries are
    never guessed.

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

    for entry in entries:
        fact = facts_by_entry_id.get(entry.id)
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

        decision = _resolve_decision(
            entry,
            entry_decisions,
            series_overrides,
            series_decisions,
        )
        if decision == SourceBackedDecision.EXCLUDE:
            excluded_positions.append(entry.position)
            continue
        if importable and decision != SourceBackedDecision.INCLUDE:
            excluded_positions.append(entry.position)
            continue

        created_now = False
        if existing_issue_id is None:
            issue = await _ensure_missing_issue_created(
                db,
                user_id,
                fact=fact,
                volume_year=entry.volume_year,
            )
            existing_issue_id = issue.id
            created_positions.append(entry.position)
            created_now = True

        node = issues_by_id.get(existing_issue_id)
        if node is None:
            node = nodes_by_id.get(f"cbl-{entry.id}")

        placement: dict[str, object] = {
            "source_path": source_path,
            "position": entry.position,
        }
        if node is not None:
            placements = _placement_list(node.get("source_cbl_placements"))
            if not _has_placement(placements, source_path):
                placements.append(placement)
                node["source_cbl_placements"] = placements
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
            "source_cbl_placements": [placement],
        }
        existing_nodes.append(new_node)
        issues_by_id[existing_issue_id] = new_node
        nodes_by_id[str(new_node["id"])] = new_node
        next_position += 1
        if not created_now:
            reused_positions.append(entry.position)

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

    existing_plan = await _find_existing_adopted_plan(db, user_id, source_path)
    if existing_plan is None:
        plan = ContinuityPlan(
            user_id=user_id,
            name=f"CBL adoption for {source_path}",
            ordering_mode="informational",
            lanes_json=_default_lane(),
            nodes_json=[],
        )
        db.add(plan)
        await db.flush()
    else:
        plan = existing_plan

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

    node_models = _to_node_models(plan.nodes_json)
    await validate_node_ownership(db, user_id=user_id, nodes=node_models)
    try:
        await replace_compiled_rules(
            db,
            user_id=user_id,
            plan=plan,
            nodes=node_models,
            ordering_mode=_plan_ordering_mode(plan),
        )
        await db.commit()
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