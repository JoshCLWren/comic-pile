"""Commit reviewed CBL material into one explicitly selected Reading Plan.

CBL is source evidence. The reader-owned Reading Plan is the target. This module
reuses the adoption/materialization mechanics from ``cbl_plan_adoption`` while
forbidding source-driven creation or discovery of a parallel Reading Plan.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache_invalidation import invalidate_user_view
from app.models.cbl_reference import CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.schemas.shared_types import SourceBackedDecision
from app.services.cbl_plan_adoption import (
    AdoptionCommitError,
    AdoptionCommitResult,
    _merge_adopted_nodes,
    _plan_ordering_mode,
    _to_node_models,
    _verify_preview_fingerprint,
)
from app.services.cbl_reconciliation import reconcile_cbl_source_list
from app.services.continuity_plan_writer import replace_compiled_rules, validate_node_ownership
from comic_pile.dependencies import refresh_user_blocked_status


def _adoption_lane_id(plan: ContinuityPlan) -> str:
    """Choose the declared lane that new targeted-adoption nodes should join."""
    lanes = list(plan.lanes_json or [])
    lane_ids = [
        str(lane["id"])
        for lane in lanes
        if isinstance(lane, dict) and lane.get("id") is not None
    ]
    if not lane_ids:
        return "default"

    declared = set(lane_ids)
    existing_nodes = [
        node
        for node in plan.nodes_json or []
        if str(node.get("lane_id")) in declared
    ]
    existing_nodes.sort(
        key=lambda node: int(node.get("position", -1))
        if isinstance(node.get("position"), int)
        else -1
    )
    if existing_nodes:
        return str(existing_nodes[-1]["lane_id"])

    ordered_lanes = sorted(
        lanes,
        key=lambda lane: int(lane.get("order", 0))
        if isinstance(lane, dict) and isinstance(lane.get("order"), int)
        else 0,
    )
    first_lane = ordered_lanes[0] if ordered_lanes else None
    if isinstance(first_lane, dict) and first_lane.get("id") is not None:
        return str(first_lane["id"])
    return "default"

async def adopt_cbl_into_existing_reading_plan(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    list_id: int,
    entry_decisions: dict[int, SourceBackedDecision],
    series_decisions: dict[str, SourceBackedDecision],
    series_overrides: dict[int, SourceBackedDecision] | None = None,
    client_content_hash: str | None = None,
    client_revision_sha: str | None = None,
) -> AdoptionCommitResult:
    """Atomically merge reviewed source material into the exact owned plan.

    The target plan must already exist and belong to ``user_id``. This function
    never creates a Reading Plan and never searches for one by CBL provenance.
    """
    plan = (
        await db.execute(
            select(ContinuityPlan)
            .where(ContinuityPlan.id == plan_id, ContinuityPlan.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if plan is None:
        raise AdoptionCommitError("Reading Plan not found")

    cbl_list = (
        await db.execute(select(CBLSourceList).where(CBLSourceList.id == list_id))
    ).scalar_one_or_none()
    if cbl_list is None:
        raise AdoptionCommitError("CBL source list not found")
    if not cbl_list.active:
        raise AdoptionCommitError("CBL source list is not active")

    if client_content_hash is not None or client_revision_sha is not None:
        await _verify_preview_fingerprint(
            cbl_list,
            client_content_hash or "",
            client_revision_sha or "",
        )

    report = await reconcile_cbl_source_list(db, list_id=list_id, user_id=user_id)
    facts_by_entry_id: dict[int, dict[str, object]] = {}
    for fact in report.entries:
        entry_id = fact.get("cbl_entry_id")
        if isinstance(entry_id, int):
            facts_by_entry_id[entry_id] = fact

    entries_result = await db.execute(
        select(CBLSourceEntry)
        .where(CBLSourceEntry.list_id == list_id)
        .order_by(CBLSourceEntry.position)
    )
    entries = list(entries_result.scalars().all())

    merge_report = await _merge_adopted_nodes(
        db,
        plan,
        user_id,
        entries,
        facts_by_entry_id,
        cbl_list.source_path,
        entry_decisions,
        series_overrides or {},
        series_decisions,
        new_node_lane_id=_adoption_lane_id(plan),
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
        await refresh_user_blocked_status(user_id, db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    await invalidate_user_view(user_id)
    await db.refresh(plan)
    return AdoptionCommitResult(
        plan=plan,
        reused_positions=merge_report.reused_positions,
        created_positions=merge_report.created_positions,
        excluded_positions=merge_report.excluded_positions,
        unresolved_positions=merge_report.unresolved_positions,
    )