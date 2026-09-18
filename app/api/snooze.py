"""Snooze API endpoints.

Routers validate input and delegate orchestration to ``SnoozeService``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models.user import User
from app.schemas import SessionResponse
from app.services.snooze_service import (
    snooze_thread as snooze_thread_service,
    unsnooze_thread as unsnooze_thread_service,
)

router = APIRouter()


@router.post("/", response_model=SessionResponse)
@limiter.limit("30/minute")
async def snooze_thread(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Snooze the pending thread and step the die up.

    This endpoint:
    1. Gets the current session (must exist with a pending_thread_id)
    2. Adds the pending_thread_id to snoozed_thread_ids
    3. Steps the die UP (wider pool) using dice ladder logic
    4. Computes a structured bandwidth correction from the snooze evidence
    5. Applies the correction to ephemeral session bandwidth state
    6. Records a "snooze" event
    7. Clears pending_thread_id
    8. Returns the updated session with correction guidance

    The snoozed thread's durable queue position is NOT changed (issue #1721).
    Rating remains the authority for long-term promotion/demotion behavior.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionResponse containing the updated session with snoozed_thread_ids,
        cleared pending_thread_id, current die state, bandwidth state, and
        structured correction guidance.

    Raises:
        HTTPException: If no active session exists or no pending thread to snooze.
    """
    _ = request
    return await snooze_thread_service(db=db, user_id=current_user.id)


@router.post("/{thread_id}/unsnooze", response_model=SessionResponse)
@limiter.limit("30/minute")
async def unsnooze_thread(
    thread_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Remove thread from snoozed list."""
    _ = request
    return await unsnooze_thread_service(db=db, user_id=current_user.id, thread_id=thread_id)
