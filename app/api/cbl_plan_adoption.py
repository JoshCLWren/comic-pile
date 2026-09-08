"""Canonical CBL adoption commit: atomic materialization of reviewed decisions into a Reading Plan.

This module implements the corrective implementation slice for #2127 under #2366.
It takes the exact reviewed CBL adoption preview/decisions from #2126 and
atomically creates/updates the existing canonical Reading Plan (`ContinuityPlan`).

Do NOT persist reader intent into `DependencyGroup` or make `DependencyGroupMembership.sequence_order` a runtime authority.

The endpoint targets one owned Reading Plan and one active CBL source list.
Revalidates the source fingerprint and reviewed entry facts at commit time;
stale preview fails with a structured conflict and no partial writes.

Reuses canonical existing issues. Materializes only explicitly approved
`missing_importable` issues, using stable external series identity and ComicVine
issue identity; fail closed rather than title-guessing.

Preserves existing issue IDs, read status, `read_at`, ratings/events/history,
thread identity, existing Reading Plan node IDs, reader overrides, checkpoints,
convergence gates, lanes, name, and ordering mode.

Adds approved source entries to the **same Reading Plan** in reviewed CBL source
order. Existing plan nodes for the same issue are reused, never duplicated.

Persists source provenance on Reading Plan nodes via existing `source_paths` /
`source_cbl_placements` fields.

CBL source position is provenance/order input only. No legacy `cbl-order:source:*`
dependencies and no new `DependencyGroup` reader-state representation.

Does not silently change `informational` to `strict_sequential`. Existing explicit
Reading Plan semantics remain authoritative.

Transactional and idempotent. Concurrent same-user/same-source adoption must
not duplicate issues or Reading Plan nodes.

Returns the updated Reading Plan plus machine-readable reused/created/excluded/
unresolved source positions.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.cbl_adoption import (
    CBLAdoptionCommitRequest,
    CBLAdoptionCommitResponse,
)
from app.schemas.continuity_plan import (
    ContinuityPlanLane,
    ContinuityPlanNode,
    PlanNodeType,
)
from app.services.cbl_plan_adoption import adopt_cbl_material_into_reading_plan

router = APIRouter(prefix="/api/v1", tags=["cbl-adoption-commit"])


@router.post(
    "/cbl/{list_id}/adoption-commit",
    response_model=CBLAdoptionCommitResponse,
    status_code=status.HTTP_200_OK,
    description="Atomically commit reviewed CBL adoption material into the existing Reading Plan.",
)
async def api_cbl_adoption_commit(
    list_id: int,
    request: CBLAdoptionCommitRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CBLAdoptionCommitResponse:
    """Commit reviewed CBL adoption material into the existing Reading Plan.

    This endpoint implements the corrective implementation slice for #2127 under #2366.
    It takes the exact reviewed CBL adoption preview/decisions from #2126 and
    atomically creates/updates the existing canonical Reading Plan (`ContinuityPlan`).

    The endpoint targets one owned Reading Plan and one active CBL source list.
    Revalidates the source fingerprint and reviewed entry facts at commit time;
    stale preview fails with a structured conflict and no partial writes.

    Reuses canonical existing issues. Materializes only explicitly approved
    `missing_importable` issues, using stable external series identity and ComicVine
    issue identity; fail closed rather than title-guessing.

    Preserves existing issue IDs, read status, `read_at`, ratings/events/history,
    thread identity, existing Reading Plan node IDs, reader overrides, checkpoints,
    convergence gates, lanes, name, and ordering mode.

    Adds approved source entries to the **same Reading Plan** in reviewed CBL source
    order. Existing plan nodes for the same issue are reused, never duplicated.

    Persists source provenance on Reading Plan nodes via existing `source_paths` /
    `source_cbl_placements` fields.

    CBL source position is provenance/order input only. No legacy `cbl-order:source:*`
    dependencies and no new `DependencyGroup` reader-state representation.

    Does not silently change `informational` to `strict_sequential`. Existing explicit
    Reading Plan semantics remain authoritative.

    Transactional and idempotent. Concurrent same-user/same-source adoption must
    not duplicate issues or Reading Plan nodes.

    Returns the updated Reading Plan plus machine-readable reused/created/excluded/
    unresolved source positions.
    """
    commit = await adopt_cbl_material_into_reading_plan(
        db,
        user_id=current_user.id,
        list_id=list_id,
        entry_decisions=request.entry_decisions,
        series_decisions={
            sd.series_name: sd.decision for sd in request.series_decisions
        },
        series_overrides={
            eo.cbl_position: eo.decision for eo in request.series_overrides
        },
        client_content_hash=request.content_hash,
        client_revision_sha=request.revision_sha,
    )
    plan = commit.plan

    def _to_continuity_plan_lane(lane: dict[str, object]) -> ContinuityPlanLane:
        """Convert a stored lane JSON dict to the response schema."""
        return ContinuityPlanLane(
            id=str(lane["id"]),
            name=str(lane["name"]),
            order=int(lane["order"]),
        )

    def _to_continuity_plan_node(node: dict[str, object]) -> ContinuityPlanNode:
        """Convert a stored node JSON dict to the response schema."""
        placements_raw = node.get("source_cbl_placements")
        source_paths: tuple[str, ...] | None = None
        if isinstance(placements_raw, list):
            paths = [
                str(raw["source_path"])
                for raw in placements_raw
                if isinstance(raw, dict) and "source_path" in raw
            ]
            if paths:
                source_paths = tuple(paths)
        return ContinuityPlanNode(
            id=str(node["id"]),
            node_type=cast(PlanNodeType, str(node["node_type"])),
            ref_id=int(node["ref_id"]),
            lane_id=str(node["lane_id"]),
            position=int(node["position"]),
            is_checkpoint=bool(node.get("is_checkpoint", False)),
            convergence_gate=list(node.get("convergence_gate") or []),
            source_paths=source_paths,
        )

    return CBLAdoptionCommitResponse(
        id=plan.id,
        user_id=plan.user_id,
        name=plan.name,
        ordering_mode=plan.ordering_mode,
        lanes=[_to_continuity_plan_lane(lane) for lane in plan.lanes_json or []],
        nodes=[_to_continuity_plan_node(node) for node in plan.nodes_json or []],
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        reused_positions=commit.reused_positions,
        created_positions=commit.created_positions,
        excluded_positions=commit.excluded_positions,
        unresolved_positions=commit.unresolved_positions,
    )