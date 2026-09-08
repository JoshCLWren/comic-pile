"""Atomic adoption of reviewed CBL entries into the canonical Reading Plan."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.schemas.continuity_plan import ContinuityPlanWrite
from app.services.cbl_reconciliation import preview_cbl_adoption
from app.services.continuity_plan_writer import apply_continuity_plan_write

CBL_PLAN_ADOPTION_LOCK_NAMESPACE = 2377001


class CBLPlanAdoptionError(Exception):
    """Base error carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize the error with a stable code and human-readable message."""
        super().__init__(message)
        self.code = code


class CBLPlanAdoptionStaleError(CBLPlanAdoptionError):
    """The reviewed source or entry facts no longer match current state."""


@dataclass(frozen=True, slots=True)
class CBLReviewedSource:
    """Source fingerprint accepted by the reader during preview."""

    source_list_id: int
    source_repository: str
    source_path: str
    content_hash: str
    revision_sha: str


@dataclass(frozen=True, slots=True)
class CBLPlanAdoptionResult:
    """Machine-readable result of one canonical-plan mutation."""

    plan_id: int
    source_list_id: int
    reused_issue_ids: tuple[int, ...]
    added_issue_ids: tuple[int, ...]
    excluded_source_positions: tuple[int, ...]
    unresolved_source_positions: tuple[int, ...]
    awaiting_opt_in_source_positions: tuple[int, ...]
    final_adopted_source_positions: tuple[int, ...]
    idempotent_replay: bool


def _reviewed_entry_facts(entry: Mapping[str, object]) -> tuple[object, ...]:
    """Return facts whose change invalidates a reviewed adoption preview."""
    return (
        entry.get("cbl_position"),
        entry.get("cbl_entry_id"),
        entry.get("series_group_id"),
        entry.get("adoption_class"),
        entry.get("adoption_decision"),
        entry.get("adopted"),
        entry.get("comicvine_issue_id"),
        entry.get("series_provider"),
        entry.get("series_external_id"),
        entry.get("resolved_issue_id"),
        entry.get("canonical_issue_id"),
        entry.get("resolution_status"),
    )


def _merge_source_provenance(
    node: dict[str, object], *, source_path: str, source_position: int
) -> dict[str, object]:
    """Merge CBL provenance while preserving every reader-owned node field."""
    updated = dict(node)
    raw_paths = node.get("source_paths")
    source_paths = [str(value) for value in raw_paths] if isinstance(raw_paths, list) else []
    if source_path not in source_paths:
        source_paths.append(source_path)

    raw_placements = node.get("source_cbl_placements")
    placement_values = raw_placements if isinstance(raw_placements, list) else []
    placements = [dict(value) for value in placement_values if isinstance(value, dict)]
    placement = {"source_path": source_path, "position": source_position}
    if placement not in placements:
        placements.append(placement)
    updated["source_paths"] = source_paths
    updated["source_cbl_placements"] = placements
    return updated


async def commit_existing_cbl_entries_to_reading_plan(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    list_id: int,
    reviewed_source: CBLReviewedSource,
    reviewed_entries: Sequence[Mapping[str, object]],
    reviewed_final_positions: Sequence[int],
    series_decisions: Mapping[str, bool],
    entry_decisions: Mapping[str, bool],
) -> CBLPlanAdoptionResult:
    """Atomically append/reuse reviewed existing issues in one canonical Reading Plan."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :user_id)"),
        {"namespace": CBL_PLAN_ADOPTION_LOCK_NAMESPACE, "user_id": user_id},
    )
    plan = (
        await db.execute(
            select(ContinuityPlan)
            .where(ContinuityPlan.id == plan_id, ContinuityPlan.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if plan is None:
        raise CBLPlanAdoptionError("reading_plan_not_found", "Reading Plan not found")
    if not plan.lanes_json:
        raise CBLPlanAdoptionError(
            "reading_plan_has_no_lane", "Reading Plan must have a lane before material can be added"
        )

    report, current = await preview_cbl_adoption(
        db,
        user_id=user_id,
        list_id=list_id,
        series_decisions=dict(series_decisions),
        entry_decisions=dict(entry_decisions),
    )
    current_source = CBLReviewedSource(
        source_list_id=int(report.source_list_id or 0),
        source_repository=str(report.source_repository or ""),
        source_path=str(report.source_path or ""),
        content_hash=str(report.content_hash or ""),
        revision_sha=str(report.revision_sha or ""),
    )
    if list_id != reviewed_source.source_list_id or current_source != reviewed_source:
        raise CBLPlanAdoptionStaleError(
            "source_fingerprint_changed",
            "The CBL source changed after preview; review the source again before committing",
        )

    current_entries = [dict(entry) for entry in current.entries]
    if len(current_entries) != len(reviewed_entries):
        raise CBLPlanAdoptionStaleError(
            "entry_count_changed", "The CBL entry set changed after preview"
        )
    for reviewed, now in zip(reviewed_entries, current_entries, strict=True):
        if _reviewed_entry_facts(reviewed) != _reviewed_entry_facts(now):
            raise CBLPlanAdoptionStaleError(
                "entry_facts_changed",
                f"CBL source position {now.get('cbl_position')} changed after preview",
            )
    if tuple(int(value) for value in reviewed_final_positions) != current.final_adopted_order:
        raise CBLPlanAdoptionStaleError(
            "adopted_positions_changed", "The reviewed CBL selection changed after preview"
        )

    selected = [entry for entry in current_entries if entry.get("adopted") is True]
    if any(entry.get("adoption_class") == "missing_importable" for entry in selected):
        raise CBLPlanAdoptionError(
            "missing_materialization_not_extracted",
            "Approved missing comics cannot be committed until the safe canonical materializer is extracted",
        )

    unresolved = tuple(
        int(entry["cbl_position"])
        for entry in current_entries
        if entry.get("adoption_decision") == "unresolved"
    )
    excluded = tuple(
        int(entry["cbl_position"])
        for entry in current_entries
        if entry.get("adoption_decision") == "excluded"
    )
    awaiting = tuple(
        int(entry["cbl_position"])
        for entry in current_entries
        if entry.get("adoption_decision") == "awaiting_opt_in"
    )

    original_nodes = [dict(node) for node in plan.nodes_json]
    nodes = [dict(node) for node in original_nodes]
    issue_node_index = {
        int(node["ref_id"]): index
        for index, node in enumerate(nodes)
        if node.get("node_type") == "issue" and isinstance(node.get("ref_id"), int)
    }
    target_lane_id = str(sorted(plan.lanes_json, key=lambda lane: int(lane["order"]))[0]["id"])
    lane_positions = [
        int(node["position"])
        for node in nodes
        if str(node.get("lane_id")) == target_lane_id
    ]
    next_position = max(lane_positions, default=-1) + 1
    reused_issue_ids: list[int] = []
    added_issue_ids: list[int] = []

    for entry in selected:
        issue_id_value = entry.get("resolved_issue_id")
        if not isinstance(issue_id_value, int):
            raise CBLPlanAdoptionError(
                "selected_entry_has_no_canonical_issue",
                f"Selected source position {entry.get('cbl_position')} has no canonical Issue",
            )
        source_position = int(entry["cbl_position"])
        existing_index = issue_node_index.get(issue_id_value)
        if existing_index is not None:
            nodes[existing_index] = _merge_source_provenance(
                nodes[existing_index],
                source_path=reviewed_source.source_path,
                source_position=source_position,
            )
            reused_issue_ids.append(issue_id_value)
            continue

        node: dict[str, object] = {
            "id": f"cbl-{list_id}-issue-{issue_id_value}",
            "node_type": "issue",
            "ref_id": issue_id_value,
            "lane_id": target_lane_id,
            "position": next_position,
            "label": f"{entry.get('series_name')} #{entry.get('issue_number')}",
            "source_paths": [reviewed_source.source_path],
            "source_cbl_placements": [
                {"source_path": reviewed_source.source_path, "position": source_position}
            ],
            "is_checkpoint": False,
            "convergence_gate": [],
        }
        nodes.append(node)
        issue_node_index[issue_id_value] = len(nodes) - 1
        next_position += 1
        added_issue_ids.append(issue_id_value)

    idempotent = nodes == original_nodes
    payload = ContinuityPlanWrite.model_validate(
        {
            "name": plan.name,
            "ordering_mode": plan.ordering_mode,
            "lanes": plan.lanes_json,
            "nodes": nodes,
        }
    )
    await apply_continuity_plan_write(db, user_id=user_id, plan=plan, payload=payload)
    await db.flush()
    await db.commit()

    return CBLPlanAdoptionResult(
        plan_id=plan.id,
        source_list_id=list_id,
        reused_issue_ids=tuple(reused_issue_ids),
        added_issue_ids=tuple(added_issue_ids),
        excluded_source_positions=excluded,
        unresolved_source_positions=unresolved,
        awaiting_opt_in_source_positions=awaiting,
        final_adopted_source_positions=current.final_adopted_order,
        idempotent_replay=idempotent,
    )
