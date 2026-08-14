"""Public preview and authenticated adoption of external crossover templates."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from app.schemas.continuity_plan import (
    ContinuityPlanResponse,
    ContinuityPlanWrite,
    CrossoverTemplateAdoptRequest,
    CrossoverTemplatePreviewRequest,
    DerivedCrossoverTemplatePreview,
)
from app.services.crossover_templates import (
    CrossoverTemplateConflict,
    CrossoverTemplateIntersection,
    CrossoverTemplateItem,
    CrossoverTemplateParallelCandidate,
    CrossoverTemplateSerialSpine,
    DerivedCrossoverTemplate,
    derive_crossover_template_from_lists,
)

router = APIRouter(tags=["crossover-templates"])


def _to_preview(
    template: DerivedCrossoverTemplate,
) -> DerivedCrossoverTemplatePreview:
    """Convert internal dataclasses into the public preview response."""
    return DerivedCrossoverTemplatePreview(
        items=[
            CrossoverTemplateItemPreview(
                issue_id=item.issue_id,
                suggested_position=item.suggested_position,
                role=item.role,
                confidence=item.confidence,
                explanation=item.explanation,
                source_paths=item.source_paths,
                target_story_arc_id=item.target_story_arc_id,
            )
            for item in template.items
        ],
        conflicts=[
            CrossoverTemplateConflictPreview(
                first_issue_id=conflict.first_issue_id,
                second_issue_id=conflict.second_issue_id,
                source_paths=conflict.source_paths,
            )
            for conflict in template.conflicts
        ],
        parallel_candidates=[
            CrossoverTemplateParallelCandidatePreview(
                first_issue_id=candidate.first_issue_id,
                second_issue_id=candidate.second_issue_id,
                source_paths=candidate.source_paths,
            )
            for candidate in template.parallel_candidates
        ],
        serial_spines=[
            CrossoverTemplateSerialSpinePreview(
                thread_id=spine.thread_id,
                issue_ids=spine.issue_ids,
                explanation=spine.explanation,
            )
            for spine in template.serial_spines
        ],
        intersections=[
            CrossoverTemplateIntersectionPreview(
                first_issue_id=intersection.first_issue_id,
                second_issue_id=intersection.second_issue_id,
                explanation=intersection.explanation,
            )
            for intersection in template.intersections
        ],
    )


@router.post(
    "/crossover-templates/preview",
    response_model=DerivedCrossoverTemplatePreview,
    description=(
        "Preview a derived crossover template from active CBL lists. "
        "Read-only: never mutates user data or continuity rules."
    ),
)
async def preview_crossover_template(
    request: CrossoverTemplatePreviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DerivedCrossoverTemplatePreview:
    """Return a non-mutating preview of a derived crossover template.

    Args:
        request: Source list IDs and optional target story-arc identifier.
        current_user: Authenticated user (reserved for future per-user
            filtering).


    db: Async database session.

    Returns:
        Advisory template with items, conflicts, parallel candidates, serial
        spines, and cross-series intersections. No continuity rules are
        created.
    """
    template = derive_crossover_template_from_lists(
        db,
        source_list_ids=request.source_list_ids,
        target_story_arc_id=request.target_story_arc_id,
    )
    return _to_preview(template)


@router.post(
    "/crossover-templates/adopt",
    response_model=ContinuityPlanResponse,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Adopt an external template into an editable continuity plan. "
        "Defaults to informational mode so no hard rules are created until "
        "the user explicitly selects blocking semantics."
    ),
)
async def adopt_crossover_template(
    request: CrossoverTemplateAdoptRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityPlanResponse:
    """Create an editable continuity plan from an external template.

    The plan defaults to informational ordering mode, storing the adopted
    positions without compiling any hard continuity rules.
    """
    template = derive_crossover_template_from_lists(
        db,
        source_list_ids=request.source_list_ids,
        target_story_arc_id=request.target_story_arc_id,
    )

    lane = {"id": request.lane_id, "name": request.lane_name, "order": 0}
    nodes = []
    for position, item in enumerate(template.items):
        result = db.execute(
            select(Issue.id)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Issue.id == item.issue_id, Thread.user_id == current_user.id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "template_item_not_owned",
                    "issue_id": item.issue_id,
                    "position": position,
                },
            )
        nodes.append(
            {
                "id": f"{request.issue_node_id_prefix}{item.issue_id}",
                "node_type": "issue",
                "ref_id": item.issue_id,
                "lane_id": request.lane_id,
                "position": position,
            }
        )

    from app.api.continuity_plan import (
        _replace_compiled_rules,
        _to_response,
        _validate_node_ownership,
        _refresh_blocked_state,
    )
    from app.models.continuity_plan import ContinuityPlan
    from app.schemas.continuity_plan import ContinuityPlanWrite

    payload = ContinuityPlanWrite(
        name=request.plan_name,
        ordering_mode=request.ordering_mode,
        lanes=[lane],
        nodes=nodes,
    )
    await _validate_node_ownership(db, user_id=current_user.id, nodes=payload.nodes)
    plan = ContinuityPlan(
        user_id=current_user.id,
        name=payload.name,
        ordering_mode=payload.ordering_mode,
        lanes_json=[lane],
        nodes_json=nodes,
    )
    db.add(plan)
    await db.flush()
    await _replace_compiled_rules(
        db, user_id=current_user.id, plan=plan, payload=payload
    )
    await db.commit()
    await db.refresh(plan)
    if request.ordering_mode == "strict_sequential":
        await _refresh_blocked_state(current_user.id, db)
    return _to_response(plan)
