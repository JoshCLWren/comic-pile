"""API endpoint for previewing a continuity-plan projection onto a reading order.

Projections are explicit two-step operations: callers request a preview of
the entries the plan would add or update, then confirm in a separate call.
The preview and confirm steps are routed to native Rust same-path handlers; this
Python router remains registered for non-native contexts and is pending cleanup
after production execution proof (#4842). The plan is never modified by a
projection, and reading order changes do not feed back into the plan (no
two-way synchronization).
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


