"""Continuity readiness evaluation endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.continuity_readiness import evaluate_continuity_readiness
from app.database import get_db
from app.models.user import User
from app.schemas.continuity_readiness import (
    ContinuityReadinessRequest,
    ContinuityReadinessResponse,
)

router = APIRouter(tags=["continuity"])


@router.post(
    "/continuity/readiness",
    response_model=ContinuityReadinessResponse,
    description="Evaluate direct continuity readiness for one owned issue, thread, or crossover.",
)
async def get_continuity_readiness(
    request: ContinuityReadinessRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityReadinessResponse:
    """Return a structured direct-readiness result for the requested owned node."""
    return await evaluate_continuity_readiness(
        db,
        user_id=current_user.id,
        node_type=request.node_type,
        node_id=request.node_id,
    )
