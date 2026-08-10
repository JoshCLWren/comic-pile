"""Mutation endpoint for accepting blocked-roll prerequisite guidance."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import _invalidate_session_caches
from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.roll_recovery_switch import switch_pending_roll_to_prerequisite
from app.schemas.roll_recovery_switch import (
    RollPrerequisiteSwitchRequest,
    RollPrerequisiteSwitchResponse,
)

router = APIRouter(tags=["roll"])


@router.post("/switch-prerequisite", response_model=RollPrerequisiteSwitchResponse)
async def switch_roll_prerequisite(
    request: RollPrerequisiteSwitchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RollPrerequisiteSwitchResponse:
    """Replace a blocked pending roll with one still-readable prerequisite issue.

    Args:
        request: Concrete issue recommendation selected by the reader.
        current_user: Authenticated ComicPile user.
        db: Async database session.

    Returns:
        The durable Roll target after accepting the prerequisite.
    """
    result = await switch_pending_roll_to_prerequisite(
        db,
        user_id=current_user.id,
        node_type=request.node_type,
        node_id=request.node_id,
    )
    await _invalidate_session_caches(current_user.id)
    return RollPrerequisiteSwitchResponse(
        original_thread_id=result.original_thread_id,
        target_thread_id=result.target_thread_id,
        target_thread_title=result.target_thread_title,
        target_issue_id=result.target_issue_id,
        target_issue_number=result.target_issue_number,
        changed=result.changed,
    )
