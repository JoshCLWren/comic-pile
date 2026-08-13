"""Authenticated continuity-plan CRUD and explicit strict-rule compilation."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.continuity_rule import _refresh_blocked_state, _would_create_cycle
from app.auth import get_current_user
from app.continuity_rules import ensure_owned_continuity_node
from app.database import get_db
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.thread import Thread
from app.models.user import User
from app.schemas.continuity_plan import (
    ContinuityPlanCheckpoint,
    ContinuityPlanGate,
    ContinuityPlanNode,
    ContinuityPlanResponse,
    ContinuityPlanWrite,
)
from app.schemas.continuity_rule import ContinuityNodeType

router = APIRouter(tags=["continuity-plans"])


def _marker(plan_id: int) -> str:
    """Return the durable ownership marker for rules compiled from one plan."""
    return f"continuity-plan:{plan_id}"


def _to_response(plan: ContinuityPlan) -> ContinuityPlanResponse:
    """Convert persisted JSON into the typed API contract."""
    return ContinuityPlanResponse(
        id=plan.id,
        user_id=plan.user_id,
        name=plan.name,
        ordering_mode=plan.ordering_mode,
        lanes=plan.lanes_json,
        nodes=plan.nodes_json,
        checkpoints=plan.checkpoints_json,
        gates=plan.gates_json,
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


async def _validate_checkpoint_references(
    db: AsyncSession,
    *,
    user_id: int,
    checkpoint: ContinuityPlanCheckpoint,
    anchor: ContinuityPlanNode,
    wait_for_issue_id: int,
) -> None:
    """Ensure the wait_for_issue_id actually belongs to the authenticated user."""
    try:
        await ensure_owned_continuity_node(
            db,
            user_id=user_id,
            node_type="issue",
            node_id=wait_for_issue_id,
        )
    except HTTPException as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "dangling_checkpoint_reference",
                "checkpoint_id": checkpoint.id,
                "after_node_id": anchor.id,
            },
        ) from exc


async def _add_strict_sequential_rules(
    db: AsyncSession,
    *,
    user_id: int,
    marker: str,
    ordered: list[ContinuityPlanNode],
) -> None:
    """Compile adjacent edges for an explicit strict-sequential plan."""
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


async def _add_checkpoint_rules(
    db: AsyncSession,
    *,
    user_id: int,
    marker: str,
    nodes_by_id: dict[str, ContinuityPlanNode],
    checkpoints: list[ContinuityPlanCheckpoint],
) -> None:
    """Compile lane-stop checkpoint rules into existing continuity_rules rows."""
    for checkpoint in checkpoints:
        anchor = nodes_by_id[checkpoint.after_node_id]
        if anchor.node_type != "issue":
            continue
        wait_for_issue_id = (
            checkpoint.wait_for_issue_id
            if checkpoint.wait_for_issue_id is not None
            else anchor.ref_id
        )
        if wait_for_issue_id != anchor.ref_id:
            await _validate_checkpoint_references(
                db,
                user_id=user_id,
                checkpoint=checkpoint,
                anchor=anchor,
                wait_for_issue_id=wait_for_issue_id,
            )
        await _compile_checkpoint_rule(
            db,
            user_id=user_id,
            marker=marker,
            checkpoint_id=checkpoint.id,
            anchor=anchor,
            wait_for_issue_id=wait_for_issue_id,
            nodes_by_id=nodes_by_id,
        )


async def _compile_checkpoint_rule(
    db: AsyncSession,
    *,
    user_id: int,
    marker: str,
    checkpoint_id: str,
    anchor: ContinuityPlanNode,
    wait_for_issue_id: int,
    nodes_by_id: dict[str, ContinuityPlanNode],
) -> None:
    """Compile a single checkpoint rule plus the edge from the wait-for issue to the anchor."""
    later = sorted(
        (
            node
            for node in nodes_by_id.values()
            if node.lane_id == anchor.lane_id and node.position > anchor.position
        ),
        key=lambda node: node.position,
    )
    if not later:
        return
    immediate = later[0]
    if immediate.node_type == "thread":
        return
    immediate_type = cast(ContinuityNodeType, immediate.node_type)
    existing = (
        await db.execute(
            select(ContinuityRule).where(
                ContinuityRule.user_id == user_id,
                ContinuityRule.source_type == "issue",
                ContinuityRule.source_id == anchor.ref_id,
                ContinuityRule.target_type == immediate_type,
                ContinuityRule.target_id == immediate.ref_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.note != marker:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "plan_rule_conflict",
                "checkpoint_id": checkpoint_id,
                "after_node_id": anchor.id,
            },
        )
    if await _would_create_cycle(
        db,
        user_id=user_id,
        source_type="issue",
        source_id=anchor.ref_id,
        target_type=immediate_type,
        target_id=immediate.ref_id,
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "continuity_cycle",
                "checkpoint_id": checkpoint_id,
                "after_node_id": anchor.id,
            },
        )
    db.add(
        ContinuityRule(
            user_id=user_id,
            source_type="issue",
            source_id=anchor.ref_id,
            target_type=immediate_type,
            target_id=immediate.ref_id,
            satisfaction_type="checkpoint",
            checkpoint_issue_id=wait_for_issue_id,
            note=marker,
        )
    )
    await db.flush()


async def _add_gate_rules(
    db: AsyncSession,
    *,
    user_id: int,
    marker: str,
    nodes_by_id: dict[str, ContinuityPlanNode],
    gates: list[ContinuityPlanGate],
) -> None:
    """Compile convergence gate rules into existing continuity_rules rows."""
    for gate in gates:
        target = nodes_by_id[gate.target_node_id]
        if target.node_type == "thread":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "gate_target_unsupported",
                    "gate_id": gate.id,
                    "target_node_id": target.id,
                },
            )
        target_type = cast(ContinuityNodeType, target.node_type)
        for required_id in gate.requires_node_ids:
            required = nodes_by_id[required_id]
            if required.node_type == "thread":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "gate_requirement_unsupported",
                        "gate_id": gate.id,
                        "requires_node_id": required.id,
                    },
                )
            required_type = cast(ContinuityNodeType, required.node_type)
            existing = (
                await db.execute(
                    select(ContinuityRule).where(
                        ContinuityRule.user_id == user_id,
                        ContinuityRule.source_type == required_type,
                        ContinuityRule.source_id == required.ref_id,
                        ContinuityRule.target_type == target_type,
                        ContinuityRule.target_id == target.ref_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None and existing.note != marker:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "plan_rule_conflict",
                        "gate_id": gate.id,
                        "requires_node_id": required.id,
                    },
                )
            if await _would_create_cycle(
                db,
                user_id=user_id,
                source_type=required_type,
                source_id=required.ref_id,
                target_type=target_type,
                target_id=target.ref_id,
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "continuity_cycle",
                        "gate_id": gate.id,
                        "requires_node_id": required.id,
                    },
                )
            db.add(
                ContinuityRule(
                    user_id=user_id,
                    source_type=required_type,
                    source_id=required.ref_id,
                    target_type=target_type,
                    target_id=target.ref_id,
                    satisfaction_type="item_read",
                    note=marker,
                )
            )
            await db.flush()


async def _replace_compiled_rules(
    db: AsyncSession,
    *,
    user_id: int,
    plan: ContinuityPlan,
    payload: ContinuityPlanWrite,
) -> bool:
    """Replace only rules owned by this plan and compile the full rule intent."""
    marker = _marker(plan.id)
    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.note == marker,
        )
    )

    nodes_by_id = {node.id: node for node in payload.nodes}
    if payload.ordering_mode == "strict_sequential" and len(payload.nodes) >= 2:
        ordered = sorted(payload.nodes, key=lambda node: node.position)
        await _add_strict_sequential_rules(
            db, user_id=user_id, marker=marker, ordered=ordered
        )
    if payload.checkpoints:
        await _add_checkpoint_rules(
            db,
            user_id=user_id,
            marker=marker,
            nodes_by_id=nodes_by_id,
            checkpoints=payload.checkpoints,
        )
    if payload.gates:
        await _add_gate_rules(
            db,
            user_id=user_id,
            marker=marker,
            nodes_by_id=nodes_by_id,
            gates=payload.gates,
        )
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
        checkpoints_json=[cp.model_dump() for cp in payload.checkpoints],
        gates_json=[gate.model_dump() for gate in payload.gates],
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
    if (
        payload.ordering_mode == "strict_sequential"
        or payload.checkpoints
        or payload.gates
    ):
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
    await _validate_node_ownership(db, user_id=current_user.id, nodes=payload.nodes)
    plan.name = payload.name
    plan.ordering_mode = payload.ordering_mode
    plan.lanes_json = [lane.model_dump() for lane in payload.lanes]
    plan.nodes_json = [node.model_dump() for node in payload.nodes]
    plan.checkpoints_json = [cp.model_dump() for cp in payload.checkpoints]
    plan.gates_json = [gate.model_dump() for gate in payload.gates]
    try:
        await _replace_compiled_rules(db, user_id=current_user.id, plan=plan, payload=payload)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(plan)
    await _refresh_blocked_state(current_user.id, db)
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
