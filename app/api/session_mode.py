"""Canonical session-mode API endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.middleware import limiter
from app.models import Session as SessionModel
from app.models.user import User
from app.schemas.session import SessionModeState, SessionModeUpdateRequest
from app.services.session_mode import MANUAL_BANDWIDTH_CONFIDENCE

router = APIRouter()


def build_session_mode_state(
    *,
    bandwidth: str | None,
    intent: str | None,
    bandwidth_source: str | None,
    intent_source: str | None,
    bandwidth_confidence: float | None,
) -> SessionModeState:
    """Project raw session-mode column values onto the canonical contract.

    Args:
        bandwidth: Active bandwidth level or None.
        intent: Active intent level or None.
        bandwidth_source: Bandwidth source or None.
        intent_source: Intent source or None.
        bandwidth_confidence: Bandwidth confidence or None.

    Returns:
        A SessionModeState with only explicitly set dimensions populated.
    """
    return SessionModeState(
        bandwidth=bandwidth,
        intent=intent,
        bandwidth_source=bandwidth_source,
        intent_source=intent_source,
        bandwidth_confidence=bandwidth_confidence,
    )


@router.put("/mode", response_model=SessionModeState)
@limiter.limit("30/minute")
async def set_session_mode(
    request: Request,
    payload: SessionModeUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionModeState:
    """Manually steer the current session's bandwidth and/or intent.

    Each dimension is independent: updating one never resets the other. Manual
    updates mark the dimension source as ``manual`` and restore full confidence
    so later Snooze evidence accumulates against an explicit reader choice.

    Args:
        request: FastAPI request object for rate limiting.
        payload: Bandwidth and/or intent values to apply.
        current_user: The authenticated user making the request.
        db: Async database session.

    Returns:
        The full canonical SessionModeState after the update.

    Raises:
        HTTPException: When no active session exists.
    """
    _ = request

    result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == current_user.id)
        .where(SessionModel.ended_at.is_(None))
        .order_by(SessionModel.started_at.desc())
    )
    current_session = result.scalars().first()
    if not current_session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session.",
        )

    if payload.bandwidth is not None:
        current_session.session_bandwidth = payload.bandwidth
        current_session.bandwidth_source = "manual"
        current_session.bandwidth_confidence = MANUAL_BANDWIDTH_CONFIDENCE
    if payload.intent is not None:
        current_session.session_intent = payload.intent
        current_session.intent_source = "manual"

    # Extract attribute values before commit; post-commit access on an expired
    # instance would trigger a lazy refresh outside the async context.
    mode_state = build_session_mode_state(
        bandwidth=current_session.session_bandwidth,
        intent=current_session.session_intent,
        bandwidth_source=current_session.bandwidth_source,
        intent_source=current_session.intent_source,
        bandwidth_confidence=current_session.bandwidth_confidence,
    )

    await db.commit()
    await invalidate_user_view(current_user.id)

    return mode_state
