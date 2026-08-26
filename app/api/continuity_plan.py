"""Authenticated continuity-plan CRUD and explicit strict-rule compilation."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.continuity_rule import _refresh_blocked_state, _would_create_cycle
from app.auth import get_current_user
from app.continuity_plan_readiness import evaluate_plan_readiness, plan_rule_marker
from app.continuity_rules import ensure_owned_continuity_node
from app.database import get_db
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.thread import Thread
from app.models.user import User
from app.schemas.continuity_plan import (
    ContinuityPlanNode,
    ContinuityPlanReadinessResponse,
    ContinuityPlanResponse,
    ContinuityPlanWrite,
)
from app.schemas.continuity_rule import ContinuityNodeType
from app.schemas.reading_order import ReadingOrderAdoptRequest

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


async def _validate_node_ownership(
    db: AsyncSession, *, user_id: int, nodes: list[ContinuityPlanNode]
) -> None:
    """Validate every referenced issue, crossover, or thread before any plan write."""
    for node in nodes:
        if node.node_type == "thread":
            owned = (
                await db.execute(
                    select(Thread.id).where(Thread.id == node.ref_id, Thread.user_id == user_id)
                )
            ).scalar_one_or_none()
            if owned is None:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "dangling_plan_reference", "node_id": node.id},
                )
            continue
        try:
            await ensure_owned_continuity_node(
                db,
                user_id=user_id,
                node_type=node.node_type,
                node_id=node.ref_id,
            )
        except HTTPException as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "dangling_plan_reference", "node_id": node.id},
            ) from exc


async def _replace_compiled_rules(
    db: AsyncSession,
    *,
    user_id: int,
    plan: ContinuityPlan,
    payload: ContinuityPlanWrite,
) -> bool:
    """Replace only rules owned by this plan and compile strict linear intent explicitly."""
    marker = _marker(plan.id)
    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.note == marker,
        )
    )
    if payload.ordering_mode != "strict_sequential" or len(payload.nodes) < 2:
        return True

    ordered = sorted(payload.nodes, key=lambda node: node.position)
    for source, target in zip(ordered, ordered[1:], strict=False):
        source_type = cast(ContinuityNodeType, source.node_type)
        target_type = cast(ContinuityNodeType, target.node_type)
        existing = (
            await db.execute(
                select(ContinuityRule).where(
                    ContinuityRule.user_id == user_id,
                    ContinuityRule.source_type == source_type,
                    ContinuityRule.source_id == source.ref_id,
                    ContinuityRule.target_type == target_type,
                    ContinuityRule.target_id == target.ref_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.note == marker:
                continue
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "plan_rule_conflict",
                    "source_node_id": source.id,
                    "target_node_id": target.id,
                },
            )
        if await _would_create_cycle(
            db,
            user_id=user_id,
            source_type=source_type,
            source_id=source.ref_id,
            target_type=target_type,
            target_id=target.ref_id,
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "continuity_cycle",
                    "source_node_id": source.id,
                    "target_node_id": target.id,
                },
            )
        db.add(
            ContinuityRule(
                user_id=user_id,
                source_type=source_type,
                source_id=source.ref_id,
                target_type=target_type,
                target_id=target.ref_id,
                satisfaction_type="item_read",
                note=marker,
            )
        )
        await db.flush()
    return True


@router.post("/continuity-plans/", response_model=ContinuityPlanResponse, status_code=201)
async def create_continuity_plan(
    payload: ContinuityPlanWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityPlanResponse:
    """Create a plan and compile rules only when strict intent is explicit."""
    await _validate_node_ownership(db, user_id=current_user.id, nodes=payload.nodes)
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
        await _replace_compiled_rules(db, user_id=current_user.id, plan=plan, payload=payload)
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


@router.get(
    "/continuity-plans/{plan_id}/readiness",
    response_model=ContinuityPlanReadinessResponse,
    description="Return live readiness for every visible node of one owned plan.",
)
async def get_continuity_plan_readiness(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    include_chains: bool = False,
) -> ContinuityPlanReadinessResponse:
    """Evaluate live per-node readiness for one owned saved plan.

    Args:
        plan_id: Identifier of the owned plan to visualize.
        current_user: Authenticated owner resolved by the API dependency.
        db: Database session supplied by the API dependency.
        include_chains: Whether to include bounded prerequisite chains for every
            blocked node so the client can explain blocking without another call.

    Returns:
        Deterministic per-node readiness aligned with the readiness API.
    """
    plan = await _get_owned_plan(db, current_user.id, plan_id)
    return await evaluate_plan_readiness(
        db,
        user_id=current_user.id,
        plan=plan,
        include_chains=include_chains,
    )


@router.put("/continuity-plans/{plan_id}", response_model=ContinuityPlanResponse)
async def update_continuity_plan(
    plan_id: int,
    payload: ContinuityPlanWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityPlanResponse:
    """Replace a plan atomically, including rules explicitly owned by that plan."""
    plan = await _get_owned_plan(db, current_user.id, plan_id)
    await _validate_node_ownership(db, user_id=current_user.id, nodes=payload.nodes)
    plan.name = payload.name
    plan.ordering_mode = payload.ordering_mode
    plan.lanes_json = [lane.model_dump() for lane in payload.lanes]
    plan.nodes_json = [node.model_dump() for node in payload.nodes]
    try:
        await _replace_compiled_rules(db, user_id=current_user.id, plan=plan, payload=payload)
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
