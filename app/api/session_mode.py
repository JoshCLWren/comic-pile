"""Canonical session reading-mode API.

Lets a reader set the ephemeral bandwidth/intent mode of one of their sessions.
The two-question quiz submits its resolved values with ``source="quiz"``; the
mode applies only to the targeted session and never blocks normal rolling.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.middleware import limiter
from app.models import Session as SessionModel
from app.models.user import User
from app.schemas.session import SessionModeResponse, SessionModeUpdateRequest
from app.services.ownership import get_owned_session_or_404

router = APIRouter(tags=["session-mode"])


def _mode_response(session: SessionModel) -> SessionModeResponse:
    """Build the response payload for a session row.

    Args:
        session: The session model to project.

    Returns:
        The session-mode response.
    """
    return SessionModeResponse(
        session_id=session.id,
        bandwidth=session.reading_bandwidth,
        intent=session.reading_intent,
        source=session.reading_mode_source,
    )


@router.get("/{session_id}/mode")
@limiter.limit("200/minute")
async def get_session_mode(
    request: Request,
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionModeResponse:
    """Return the current reading-mode state of an owned session.

    Args:
        request: FastAPI request object for rate limiting.
        session_id: The session whose mode should be returned.
        current_user: The authenticated user making the request.
        db: Async database session.

    Returns:
        The session's bandwidth, intent, and setting source (each may be None).

    Raises:
        HTTPException: If the session does not exist or is not owned by the user.
    """
    session = await get_owned_session_or_404(db, current_user.id, session_id)
    return _mode_response(session)


@router.post("/{session_id}/mode")
@limiter.limit("60/minute")
async def set_session_mode(
    request: Request,
    session_id: int,
    payload: SessionModeUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionModeResponse:
    """Set the reading-mode state of an owned session.

    Quiz submissions send both resolved axes with ``source="quiz"``. Partial
    updates are allowed so future manual controls can adjust one axis without
    disturbing the other.

    Args:
        request: FastAPI request object for rate limiting.
        session_id: The session to update.
        payload: The validated mode update (bandwidth and/or intent plus source).
        current_user: The authenticated user making the request.
        db: Async database session.

    Returns:
        The resulting session-mode state.

    Raises:
        HTTPException: If the session does not exist, is not owned by the user,
            or has already ended.
    """
    session = await get_owned_session_or_404(db, current_user.id, session_id)

    if session.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session {session_id} has already ended",
        )

    if payload.bandwidth is not None:
        session.reading_bandwidth = payload.bandwidth
    if payload.intent is not None:
        session.reading_intent = payload.intent
    session.reading_mode_source = payload.source

    # Extract before commit; attribute access after commit would expire the row.
    response = _mode_response(session)

    await db.commit()
    await invalidate_user_view(current_user.id)

    return response
