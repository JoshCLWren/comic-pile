"""Authenticated continuity-plan CRUD and explicit strict-rule compilation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.continuity_rule import _refresh_blocked_state
from app.auth import get_current_user
from app.database import get_db
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.user import User
from app.repositories.continuity_repository import plans_for_user
from app.schemas.continuity_plan import (
    ContinuityPlanListItem,
    ContinuityPlanResponse,
    ContinuityPlanWrite,
)
from app.schemas.reading_order import ReadingOrderAdoptRequest
from app.services.continuity_plan_writer import (
    plan_rule_marker,
    replace_compiled_rules,
    validate_node_ownership,
)

router = APIRouter(tags=["continuity-plans"])


def _marker(plan_id: int) -> str:
    """Return the durable ownership marker for rules compiled from one plan."""
    return plan_rule_marker(plan_id)


def _to_response(plan: ContinuityPlan) -> ContinuityPlanResponse:
    """Convert persisted JSON into the typed API contract."""
    return ContinuityPlanResponse(
        id=plan.id,
        user_id=plan.user_id,
        name=plan.name,
        ordering_mode=plan.ordering_mode,
        lanes=plan.lanes_json,
        nodes=plan.nodes_json,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _source_paths(plan: ContinuityPlan) -> list[str]:
    """Return unique CBL source paths retained by plan nodes in source order."""
    paths: list[str] = []
    for node in plan.nodes_json or []:
        placements = node.get("source_cbl_placements")
        if isinstance(placements, list):
            for placement in placements:
                if not isinstance(placement, dict):
                    continue
                path = placement.get("source_path")
                if isinstance(path, str) and path not in paths:
                    paths.append(path)
        source_paths = node.get("source_paths")
        if isinstance(source_paths, (list, tuple)):
            for path in source_paths:
                if isinstance(path, str) and path not in paths:
                    paths.append(path)
    return paths


async def _get_owned_plan(db: AsyncSession, user_id: int, plan_id: int) -> ContinuityPlan:
    """Load one plan without leaking another user's identifiers."""
    plan = (
        await db.execute(
            select(ContinuityPlan).where(
                ContinuityPlan.id == plan_id,
                ContinuityPlan.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Continuity plan {plan_id} not found")
    return plan


@router.get("/continuity-plans/", response_model=list[ContinuityPlanListItem])
async def list_continuity_plans(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ContinuityPlanListItem]:
    """List every continuity plan owned by the authenticated user.

    Plans are returned in descending ``updated_at`` order so the most
    recently modified plan appears first.
    """
    rows = await plans_for_user(db, user_id=current_user.id)
    ordered = sorted(rows, key=lambda plan: plan.updated_at, reverse=True)
    return [
        ContinuityPlanListItem(
            id=plan.id,
            name=plan.name,
            ordering_mode=plan.ordering_mode,
            lane_count=len(plan.lanes_json),
            step_count=len(plan.nodes_json),
            source_paths=_source_paths(plan),
            updated_at=plan.updated_at,
        )
        for plan in ordered
    ]


@router.post("/continuity-plans/", response_model=ContinuityPlanResponse, status_code=201)
async def create_continuity_plan(
    payload: ContinuityPlanWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityPlanResponse:
    """Create a plan and compile rules only when strict intent is explicit."""
    await validate_node_ownership(db, user_id=current_user.id, nodes=payload.nodes)
    plan = ContinuityPlan(
        user_id=current_user.id,
        name=payload.name,
        ordering_mode=payload.ordering_mode,
        lanes_json=[lane.model_dump() for lane in payload.lanes],
        nodes_json=[node.model_dump() for node in payload.nodes],
    )
    db.add(plan)
    await db.flush()
    try:
        await replace_compiled_rules(
            db,
            user_id=current_user.id,
            plan=plan,
            nodes=payload.nodes,
            ordering_mode=payload.ordering_mode,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(plan)
    if payload.ordering_mode == "strict_sequential":
        await _refresh_blocked_state(current_user.id, db)
    return _to_response(plan)


@router.get("/continuity-plans/{plan_id}", response_model=ContinuityPlanResponse)
async def get_continuity_plan(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityPlanResponse:
    """Return one owned continuity plan."""
    return _to_response(await _get_owned_plan(db, current_user.id, plan_id))



@router.put("/continuity-plans/{plan_id}", response_model=ContinuityPlanResponse)
async def update_continuity_plan(
    plan_id: int,
    payload: ContinuityPlanWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityPlanResponse:
    """Replace a plan atomically, including rules explicitly owned by that plan."""
    plan = await _get_owned_plan(db, current_user.id, plan_id)
    await validate_node_ownership(db, user_id=current_user.id, nodes=payload.nodes)
    plan.name = payload.name
    plan.ordering_mode = payload.ordering_mode
    plan.lanes_json = [lane.model_dump() for lane in payload.lanes]
    plan.nodes_json = [node.model_dump() for node in payload.nodes]
    try:
        await replace_compiled_rules(
            db,
            user_id=current_user.id,
            plan=plan,
            nodes=payload.nodes,
            ordering_mode=payload.ordering_mode,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(plan)
    await _refresh_blocked_state(current_user.id, db)
    return _to_response(plan)


@router.post(
    "/continuity-plans/from-reading-order",
    response_model=ContinuityPlanResponse,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Adopt a legacy reading order into the canonical continuity plan. "
        "The source reading order is not mutated; the new plan is the "
        "canonical owner of the ordering intent. See "
        "docs/READING_PLAN_CANONICAL_MODEL.md."
    ),
)
async def adopt_reading_order(
    payload: ReadingOrderAdoptRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityPlanResponse:
    """Create a canonical plan from one owned legacy reading order."""
    from app.services.reading_order_adoption import adopt_reading_order_to_plan

    plan = await adopt_reading_order_to_plan(
        db,
        user_id=current_user.id,
        reading_order_id=payload.reading_order_id,
        plan_name=payload.plan_name,
        lane_id=payload.lane_id,
        lane_name=payload.lane_name,
    )
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(plan)
    return _to_response(plan)


@router.delete("/continuity-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_continuity_plan(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Delete one plan and only the hard rules compiled by that plan."""
    plan = await _get_owned_plan(db, current_user.id, plan_id)
    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == current_user.id,
            ContinuityRule.note == _marker(plan.id),
        )
    )
    await db.delete(plan)
    await db.commit()
    await _refresh_blocked_state(current_user.id, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
