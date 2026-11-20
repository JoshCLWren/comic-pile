"""API endpoints for projecting a continuity plan into an existing reading order.

Projections are explicit two-step operations: callers request a preview of
the entries the plan would add or update, then confirm in a separate call.
The plan is never modified by a projection, and reading order changes do
not feed back into the plan (no two-way synchronization).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.reading_order import (
    ReadingOrderProjectionPreview,
    ReadingOrderProjectionRequest,
    ReadingOrderProjectionResult,
)
from app.services import reading_order_projection

router = APIRouter(tags=["reading-orders"])


@router.post(
    "/continuity-plans/{plan_id}/reading-orders/project-preview",
    response_model=ReadingOrderProjectionPreview,
)
async def preview_plan_projection(
    plan_id: int,
    payload: ReadingOrderProjectionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingOrderProjectionPreview:
    """Preview a deterministic projection without mutating any resource.

    The preview is recomputed from the persisted plan JSON on every call so
    that callers always see the current state, even after concurrent edits.
    Duplicate thread references, missing owned threads, and non-thread
    nodes are reported as conflicts before any mutation is permitted.
    """
    projection = await reading_order_projection.build_projection_plan(
        db,
        user_id=current_user.id,
        plan_id=plan_id,
        reading_order_id=payload.reading_order_id,
    )
    return await reading_order_projection.preview_to_response(projection)


@router.post(
    "/continuity-plans/{plan_id}/reading-orders/project",
    response_model=ReadingOrderProjectionResult,
)
async def confirm_plan_projection(
    plan_id: int,
    payload: ReadingOrderProjectionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingOrderProjectionResult:
    """Apply a projection atomically after a successful preview.

    The confirm endpoint re-computes the projection and rejects the request
    if any conflict is detected. A failed or cancelled projection leaves
    both the plan and the reading order unchanged because all mutations are
    performed in a single transaction that rolls back on any error.
    """
    outcome = await reading_order_projection.apply_projection(
        db,
        user_id=current_user.id,
        plan_id=plan_id,
        reading_order_id=payload.reading_order_id,
    )
    return await reading_order_projection.outcome_to_response(outcome)
