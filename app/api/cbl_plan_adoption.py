"""Canonical CBL adoption commit into an explicitly selected Reading Plan."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.cbl_adoption import CBLAdoptionCommitRequest, CBLAdoptionCommitResponse
from app.schemas.continuity_plan import ContinuityPlanLane, ContinuityPlanNode, PlanNodeType
from app.services.cbl_plan_adoption import AdoptionCommitError, StalePreviewError
from app.services.cbl_targeted_plan_adoption import adopt_cbl_into_existing_reading_plan

router = APIRouter(prefix="/api/v1", tags=["cbl-adoption-commit"])


@router.post(
    "/cbl/{list_id}/reading-plans/{plan_id}/adoption-commit",
    response_model=CBLAdoptionCommitResponse,
    status_code=status.HTTP_200_OK,
    description="Atomically commit reviewed CBL material into the selected existing Reading Plan.",
)
async def api_cbl_adoption_commit(
    list_id: int,
    plan_id: int,
    request: CBLAdoptionCommitRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CBLAdoptionCommitResponse:
    """Commit reviewed source material into the exact owned Reading Plan."""
    try:
        commit = await adopt_cbl_into_existing_reading_plan(
            db,
            user_id=current_user.id,
            plan_id=plan_id,
            list_id=list_id,
            entry_decisions=request.entry_decisions,
            series_decisions={sd.series_name: sd.decision for sd in request.series_decisions},
            series_overrides={eo.cbl_position: eo.decision for eo in request.series_overrides},
            client_content_hash=request.content_hash,
            client_revision_sha=request.revision_sha,
        )
    except StalePreviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except AdoptionCommitError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "Reading Plan not found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": "adoption_error", "message": str(exc)},
        ) from exc

    plan = commit.plan

    def _to_continuity_plan_lane(lane: dict[str, object]) -> ContinuityPlanLane:
        return ContinuityPlanLane(
            id=str(lane["id"]),
            name=str(lane["name"]),
            order=int(lane["order"]),
        )

    def _to_continuity_plan_node(node: dict[str, object]) -> ContinuityPlanNode:
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