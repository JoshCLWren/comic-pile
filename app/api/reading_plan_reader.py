"""Reader-facing Reading Plan progress and availability endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.reading_plan_reader import ReadingPlanReaderResponse
from app.services.reading_plan_reader import get_reading_plan_reader

router = APIRouter(tags=["continuity-plans"])


@router.get(
    "/continuity-plans/{plan_id}/reader",
    response_model=ReadingPlanReaderResponse,
)
async def get_continuity_plan_reader(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingPlanReaderResponse:
    """Return progress, available now, blocked next, and ordered lanes.

    Blocking uses canonical issue-level Dependencies only. The payload is the
    primary reader view for a Reading Plan and does not change Roll eligibility.
    """
    return await get_reading_plan_reader(
        db, user_id=current_user.id, plan_id=plan_id
    )
