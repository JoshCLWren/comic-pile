"""Canonical CBL adoption endpoints for Reading Plans."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.cbl_adoption import CBLAdoptionCommitRequest, CBLAdoptionCommitResponse
from app.schemas.continuity_plan import ContinuityPlanLane, ContinuityPlanNode
from app.schemas.shared_types import SourceBackedDecision
from app.services.cbl_plan_adoption import (
    AdoptionCommitError,
    AdoptionCommitResult,
    StalePreviewError,
    adopt_cbl_material_into_reading_plan,
)
from app.services.cbl_targeted_plan_adoption import adopt_cbl_into_existing_reading_plan

router = APIRouter(prefix="/api/v1", tags=["cbl-adoption-commit"])


def _response(commit: AdoptionCommitResult) -> CBLAdoptionCommitResponse:
    """Convert one adoption result to the public response schema."""
    plan = commit.plan

    def lane(value: dict[str, object]) -> ContinuityPlanLane:
        return ContinuityPlanLane(
            id=str(value["id"]), name=str(value["name"]), order=int(value["order"])
        )

    def node(value: dict[str, object]) -> ContinuityPlanNode:
        return ContinuityPlanNode.model_validate(value)

    return CBLAdoptionCommitResponse(
        id=plan.id,
        user_id=plan.user_id,
        name=plan.name,
        ordering_mode=plan.ordering_mode,
        lanes=[lane(value) for value in plan.lanes_json or []],
        nodes=[node(value) for value in plan.nodes_json or []],
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        reused_positions=commit.reused_positions,
        created_positions=commit.created_positions,
        excluded_positions=commit.excluded_positions,
        unresolved_positions=commit.unresolved_positions,
    )


def _decisions(
    request: CBLAdoptionCommitRequest,
) -> tuple[dict[str, SourceBackedDecision], dict[int, SourceBackedDecision]]:
    """Normalize request decisions for the service boundary."""
    return (
        {item.series_name: item.decision for item in request.series_decisions},
        {item.cbl_position: item.decision for item in request.series_overrides},
    )


@router.post(
    "/cbl/{list_id}/reading-plans/{plan_id}/adoption-commit",
    response_model=CBLAdoptionCommitResponse,
    status_code=status.HTTP_200_OK,
    description="Commit reviewed CBL material into the exact existing Reading Plan.",
)
async def api_targeted_cbl_adoption_commit(
    list_id: int,
    plan_id: int,
    request: CBLAdoptionCommitRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CBLAdoptionCommitResponse:
    """Commit to the caller-selected owned Reading Plan and never create another."""
    series_decisions, series_overrides = _decisions(request)
    try:
        commit = await adopt_cbl_into_existing_reading_plan(
            db,
            user_id=current_user.id,
            plan_id=plan_id,
            list_id=list_id,
            entry_decisions=request.entry_decisions,
            series_decisions=series_decisions,
            series_overrides=series_overrides,
            client_content_hash=request.content_hash,
            client_revision_sha=request.revision_sha,
        )
    except StalePreviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except AdoptionCommitError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "adoption_error", "message": str(exc)},
        ) from exc
    return _response(commit)


async def api_cbl_adoption_commit(
    list_id: int,
    request: CBLAdoptionCommitRequest,
    current_user: User,
    db: AsyncSession,
) -> CBLAdoptionCommitResponse:
    """Compatibility shim for pre-targeting unit callers; this is not an HTTP route."""
    series_decisions, series_overrides = _decisions(request)
    try:
        commit = await adopt_cbl_material_into_reading_plan(
            db,
            user_id=current_user.id,
            list_id=list_id,
            entry_decisions=request.entry_decisions,
            series_decisions=series_decisions,
            series_overrides=series_overrides,
            client_content_hash=request.content_hash,
            client_revision_sha=request.revision_sha,
        )
    except StalePreviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except AdoptionCommitError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "adoption_error", "message": str(exc)},
        ) from exc
    return _response(commit)
