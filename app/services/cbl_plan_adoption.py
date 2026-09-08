"""Atomic adoption of reviewed CBL entries into the canonical Reading Plan."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache_invalidation import invalidate_user_view
from app.models.continuity_plan import ContinuityPlan
from app.schemas.continuity_plan import ContinuityPlanWrite
from app.services.cbl_issue_materializer import CBLMaterializationError, materialize_cbl_entries
from app.services.cbl_reconciliation import preview_cbl_adoption
from app.services.continuity_plan_writer import apply_continuity_plan_write
from comic_pile.dependencies import refresh_user_blocked_status

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
    created_issue_ids: tuple[int, ...]
    created_thread_ids: tuple[int, ...]
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


def _entry_matches_review(
    reviewed: Mapping[str, object],
    current: Mapping[str, object],
    replay_issue_id: int | None,
) -> bool:
    """Accept exact reviewed facts or the exact missing→existing replay transition."""
    if _reviewed_entry_facts(reviewed) == _reviewed_entry_facts(current):
        return True
    return bool(
        reviewed.get("adoption_class") == "missing_importable"
        and reviewed.get("adoption_decision") == "would_create_missing"
        and reviewed.get("adopted") is True
        and current.get("adoption_class") == "existing"
        and current.get("adoption_decision") == "included_existing"
        and current.get("adopted") is True
        and reviewed.get("cbl_position") == current.get("cbl_position")
        and reviewed.get("cbl_entry_id") == current.get("cbl_entry_id")
        and reviewed.get("series_group_id") == current.get("series_group_id")
        and reviewed.get("series_provider") == current.get("series_provider")
        and reviewed.get("series_external_id") == current.get("series_external_id")
        and reviewed.get("comicvine_issue_id") == current.get("comicvine_issue_id")
        and current.get("resolved_issue_id") == replay_issue_id
        and current.get("canonical_issue_id") == replay_issue_id
    )


def _replay_issue_ids_by_source_position(
    plan: ContinuityPlan, *, source_path: str
) -> dict[int, int]:
    """Return source positions already represented by issue nodes in this plan."""
    result: dict[int, int] = {}
    for node in plan.nodes_json:
        if node.get("node_type") != "issue" or not isinstance(node.get("ref_id"), int):
            continue
        placements = node.get("source_cbl_placements")
        if not isinstance(placements, list):
            continue
        for placement in placements:
            if not isinstance(placement, dict) or placement.get("source_path") != source_path:
                continue
            position = placement.get("position")
            if isinstance(position, int):
                result[position] = int(node["ref_id"])
    return result


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
    """Atomically materialize and adopt reviewed CBL entries into one Reading Plan."""
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
    replay_issue_ids = _replay_issue_ids_by_source_position(
        plan, source_path=reviewed_source.source_path
    )
    for reviewed, now in zip(reviewed_entries, current_entries, strict=True):
        position = int(now.get("cbl_position") or 0)
        if not _entry_matches_review(reviewed, now, replay_issue_ids.get(position)):
            raise CBLPlanAdoptionStaleError(
                "entry_facts_changed",
                f"CBL source position {now.get('cbl_position')} changed after preview",
            )
    if tuple(int(value) for value in reviewed_final_positions) != current.final_adopted_order:
        raise CBLPlanAdoptionStaleError(
            "adopted_positions_changed", "The reviewed CBL selection changed after preview"
        )

    selected = [entry for entry in current_entries if entry.get("adopted") is True]
    missing = [entry for entry in selected if entry.get("adoption_class") == "missing_importable"]
    try:
        materialized = await materialize_cbl_entries(db, user_id=user_id, entries=missing)
    except CBLMaterializationError as exc:
        raise CBLPlanAdoptionError("missing_materialization_failed", str(exc)) from exc

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
    reused_issue_ids: list[int] = list(materialized.reused_issue_ids)
    added_issue_ids: list[int] = []

    for entry in selected:
        source_position = int(entry["cbl_position"])
        issue_id_value = entry.get("resolved_issue_id")
        if not isinstance(issue_id_value, int):
            issue_id_value = materialized.issue_ids_by_source_position.get(source_position)
        if not isinstance(issue_id_value, int):
            raise CBLPlanAdoptionError(
                "selected_entry_has_no_canonical_issue",
                f"Selected source position {source_position} has no canonical Issue",
            )
        existing_index = issue_node_index.get(issue_id_value)
        if existing_index is not None:
            nodes[existing_index] = _merge_source_provenance(
                nodes[existing_index],
                source_path=reviewed_source.source_path,
                source_position=source_position,
            )
            if issue_id_value not in reused_issue_ids:
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

    idempotent = (
        nodes == original_nodes
        and not materialized.created_issue_ids
        and not materialized.created_thread_ids
    )
    payload = ContinuityPlanWrite.model_validate(
        {
            "name": plan.name,
            "ordering_mode": plan.ordering_mode,
            "lanes": plan.lanes_json,
            "nodes": nodes,
        }
    )
    try:
        await apply_continuity_plan_write(db, user_id=user_id, plan=plan, payload=payload)
        if payload.ordering_mode == "strict_sequential":
            await refresh_user_blocked_status(user_id, db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await invalidate_user_view(user_id)

    return CBLPlanAdoptionResult(
        plan_id=plan.id,
        source_list_id=list_id,
        reused_issue_ids=tuple(reused_issue_ids),
        added_issue_ids=tuple(added_issue_ids),
        created_issue_ids=materialized.created_issue_ids,
        created_thread_ids=materialized.created_thread_ids,
        excluded_source_positions=excluded,
        unresolved_source_positions=unresolved,
        awaiting_opt_in_source_positions=awaiting,
        final_adopted_source_positions=current.final_adopted_order,
        idempotent_replay=idempotent,
    )
