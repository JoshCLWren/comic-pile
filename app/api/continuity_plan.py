"""Authenticated continuity-plan CRUD and explicit strict-rule compilation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.continuity_plan import ContinuityPlan
from app.models.user import User
from app.repositories.continuity_repository import (
    delete_continuity_plan_rules_for_marker,
    get_continuity_plan as repo_get_continuity_plan,
)
from app.schemas.continuity_plan import (
    ContinuityPlanListItem,
    ContinuityPlanResponse,
    ContinuityPlanWrite,
)
from app.schemas.reading_order import ReadingOrderAdoptRequest
from app.schemas.reading_plan_membership import (
    ReadingPlanDependencyLink,
    ReadingPlanDependencyLinkRequest,
    ReadingPlanMembershipResponse,
)
from app.schemas.tags import TagTargetType
from app.services.continuity import _refresh_blocked_state
from app.services.continuity_plan_writer import (
    guard_plan_update,
    list_continuity_plan_items,
    payload_issue_ids,
    plan_rule_marker,
    preserve_checkpoint_targets,
    preserve_server_lane_metadata,
    replace_compiled_rules,
    retire_plan_edges_for_deletion,
    serialize_new_plan_lanes,
    validate_node_ownership,
)
from app.services.reading_plan_normalization import (
    editor_nodes_for_plan,
    editor_plan_response,
    get_plan_membership,
    is_identity_editor_payload,
    link_dependency_to_plan,
    unlink_dependency_from_plan,
)
from app.services.tag_service import purge_target_assignments
from app.config import get_reading_execution_settings
from app.services.reading_plan_list_link import link_new_plan_to_owned_list

router = APIRouter(tags=["continuity-plans"])


def _marker(plan_id: int) -> str:
    """Return the durable ownership marker for rules compiled from one plan."""
    return plan_rule_marker(plan_id)


async def _get_owned_plan(db: AsyncSession, user_id: int, plan_id: int) -> ContinuityPlan:
    """Load one plan without leaking another user's identifiers."""
    plan = await repo_get_continuity_plan(db, user_id=user_id, plan_id=plan_id)
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
    return await list_continuity_plan_items(db, user_id=current_user.id)


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
        lanes_json=serialize_new_plan_lanes(payload.lanes),
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
        if get_reading_execution_settings().enabled:
            await link_new_plan_to_owned_list(
                db, plan=plan, user_id=current_user.id,
            )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "continuity_cbl_collision", "message": str(exc)},
        ) from exc
    except Exception:
        await db.rollback()
        raise
    await db.refresh(plan)
    # Always refresh: informational plans with checkpoint/convergence gates
    # also compile canonical edges via the write-path hook (#2553).
    await _refresh_blocked_state(current_user.id, db)
    return await editor_plan_response(db, plan)


@router.get("/continuity-plans/{plan_id}", response_model=ContinuityPlanResponse)
async def get_continuity_plan(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityPlanResponse:
    """Return one owned continuity plan from normalized membership."""
    return await editor_plan_response(
        db, await _get_owned_plan(db, current_user.id, plan_id)
    )


@router.get(
    "/continuity-plans/{plan_id}/membership",
    response_model=ReadingPlanMembershipResponse,
)
async def get_continuity_plan_membership(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingPlanMembershipResponse:
    """Return the normalized membership view for one owned plan.

    Membership, Dependency provenance, source snapshots, placements, and
    progress derived from global Issue read state are read through the
    normalized relational representation.
    """
    return await get_plan_membership(db, user_id=current_user.id, plan_id=plan_id)


@router.post(
    "/continuity-plans/{plan_id}/dependencies/{dependency_id}",
    response_model=ReadingPlanDependencyLink,
    status_code=status.HTTP_201_CREATED,
)
async def link_plan_dependency_edge(
    plan_id: int,
    dependency_id: int,
    payload: ReadingPlanDependencyLinkRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingPlanDependencyLink:
    """Reference one canonical Dependency edge from one owned plan.

    Linking records provenance only; it never creates, modifies, or deletes
    the canonical edge and never changes Roll eligibility.
    """
    _, linked_id, source_id, target_id, explanation_value = (
        await link_dependency_to_plan(
            db,
            user_id=current_user.id,
            plan_id=plan_id,
            dependency_id=dependency_id,
            explanation=payload.explanation,
        )
    )
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return ReadingPlanDependencyLink(
        dependency_id=linked_id,
        source_issue_id=source_id,
        target_issue_id=target_id,
        explanation=explanation_value,
    )


@router.delete(
    "/continuity-plans/{plan_id}/dependencies/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_plan_dependency_edge(
    plan_id: int,
    dependency_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Remove one plan's reference to a Dependency edge.

    Only this plan's link is removed; the canonical edge and every other
    plan's references are untouched.
    """
    removed = await unlink_dependency_from_plan(
        db, user_id=current_user.id, plan_id=plan_id, dependency_id=dependency_id
    )
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"Dependency {dependency_id} is not referenced by plan {plan_id}",
        )
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/continuity-plans/{plan_id}", response_model=ContinuityPlanResponse)
async def update_continuity_plan(
    plan_id: int,
    payload: ContinuityPlanWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityPlanResponse:
    """Replace a legacy Plan; Option E edits must use the authoritative List."""
    plan = await _get_owned_plan(db, current_user.id, plan_id)
    if get_reading_execution_settings().enabled:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reading_list_is_authoritative",
                "message": "Edit the linked Reading List, not the legacy Plan order",
            },
        )
    await validate_node_ownership(db, user_id=current_user.id, nodes=payload.nodes)
    membership_ids = await guard_plan_update(db, plan=plan, payload=payload)
    prior_ordering_mode = plan.ordering_mode
    plan.name = payload.name
    plan.ordering_mode = payload.ordering_mode
    plan.lanes_json = preserve_server_lane_metadata(
        list(plan.lanes_json or []),
        payload.lanes,
    )
    # An ordinary GET-then-save of the membership overlay must not collapse
    # leftover nodes_json. A real editor change (lane, order, checkpoint,
    # convergence, or membership) rewrites stored JSON.
    current_editor = await editor_nodes_for_plan(db, plan)
    payload.nodes = preserve_checkpoint_targets(current_editor, payload.nodes)
    if (
        payload_issue_ids(payload.nodes) != membership_ids
        or not is_identity_editor_payload(current_editor, payload.nodes)
    ):
        plan.nodes_json = [node.model_dump() for node in payload.nodes]
    try:
        await replace_compiled_rules(
            db,
            user_id=current_user.id,
            plan=plan,
            nodes=payload.nodes,
            ordering_mode=payload.ordering_mode,
            prior_ordering_mode=prior_ordering_mode,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "continuity_cbl_collision", "message": str(exc)},
        ) from exc
    except Exception:
        await db.rollback()
        raise
    await db.refresh(plan)
    await _refresh_blocked_state(current_user.id, db)
    return await editor_plan_response(db, plan)


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
    return await editor_plan_response(db, plan)


@router.delete("/continuity-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_continuity_plan(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Delete one plan and only the hard rules compiled by that plan."""
    plan = await _get_owned_plan(db, current_user.id, plan_id)
    # Retire the plan's compiled canonical edges before deleting its rules:
    # after the cutover those Dependency rows are the only Roll authority.
    await retire_plan_edges_for_deletion(
        db, user_id=current_user.id, plan_id=plan.id
    )
    await delete_continuity_plan_rules_for_marker(
        db, user_id=current_user.id, marker=_marker(plan.id)
    )
    # Tag assignments point at polymorphic target ids with no foreign key.
    await purge_target_assignments(db, TagTargetType.CONTINUITY_PLAN.value, [plan.id])
    await db.delete(plan)
    await db.commit()
    await _refresh_blocked_state(current_user.id, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
