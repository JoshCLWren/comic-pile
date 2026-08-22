"""Reading-mode API endpoints.

Exposes the two-question reading-mode quiz results and manual mode-selector
entries. Both flows write only to the active session and record the source
(``quiz`` or ``manual``) so the rest of the app can distinguish them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.middleware import limiter
from app.models import Session as SessionModel
from app.models.user import User
from app.services.reading_quiz import (
    QuizResolutionError,
    ReadingModeSource,
    resolve_quiz_answers,
)

router = APIRouter(tags=["reading-mode"])


class ReadingModeSetRequest(BaseModel):
    """Request to set the active session reading mode.

    Callers may submit resolved ``bandwidth``/``intent`` directly (manual
    selector), or submit raw quiz ``answers`` with ``source="quiz"`` and let the
    server resolve them through the canonical contract.
    """

    bandwidth: str | None = Field(default=None, description="Resolved bandwidth value")
    intent: str | None = Field(default=None, description="Resolved intent value")
    answers: dict[str, str] | None = Field(
        default=None, description="Raw quiz answers keyed by question ID"
    )
    source: str = Field(..., description="Origin of the setting: 'quiz' or 'manual'")

    def resolve_bandwidth_intent(self) -> tuple[str, str]:
        """Resolve the request into a valid (bandwidth, intent) pair.

        Returns:
            Tuple of validated bandwidth and intent strings.

        Raises:
            QuizResolutionError: If the answers cannot be resolved.
            HTTPException: If neither answers nor both bandwidth/intent are present.
        """
        if self.answers:
            mode = resolve_quiz_answers(self.answers)
            return mode.bandwidth, mode.intent
        if self.bandwidth and self.intent:
            return self.bandwidth, self.intent
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either quiz answers or both bandwidth and intent",
        )


class ReadingModeResponse(BaseModel):
    """Current reading-mode state for the active session."""

    bandwidth: str | None
    intent: str | None
    source: str | None
    suggested: bool


async def _get_active_session(db: AsyncSession, user: User) -> SessionModel:
    """Return the active session for the current user, creating one if needed."""
    from comic_pile.session import get_or_create

    return await get_or_create(db, user_id=user.id, existing_user=user)


@router.get("/api/v1/reading-mode")
@limiter.limit("200/minute")
async def get_reading_mode(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ReadingModeResponse:
    """Return the active session's current reading mode.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        The current reading-mode state.
    """
    session = await _get_active_session(db, current_user)
    return ReadingModeResponse(
        bandwidth=session.reading_bandwidth,
        intent=session.reading_intent,
        source=session.reading_mode_source,
        suggested=session.reading_mode_suggested,
    )


@router.post("/api/v1/reading-mode")
@limiter.limit("60/minute")
async def set_reading_mode(
    request: Request,
    payload: ReadingModeSetRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ReadingModeResponse:
    """Set the active session reading mode.

    Args:
        request: FastAPI request object for rate limiting.
        payload: The reading-mode set request.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        The newly stored reading-mode state.

    Raises:
        HTTPException: If the source is invalid or resolution fails.
    """
    if payload.source not in ReadingModeSource.values():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid reading-mode source: {payload.source!r}",
        )

    try:
        bandwidth, intent = payload.resolve_bandwidth_intent()
    except QuizResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    session = await _get_active_session(db, current_user)
    session.reading_bandwidth = bandwidth
    session.reading_intent = intent
    session.reading_mode_source = payload.source
    session.reading_mode_suggested = False

    await db.commit()
    await db.refresh(session)
    await invalidate_user_view(current_user.id)

    return ReadingModeResponse(
        bandwidth=session.reading_bandwidth,
        intent=session.reading_intent,
        source=session.reading_mode_source,
        suggested=session.reading_mode_suggested,
    )


@router.post("/api/v1/reading-mode/dismiss-suggestion")
@limiter.limit("60/minute")
async def dismiss_reading_mode_suggestion(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ReadingModeResponse:
    """Dismiss the reading-mode suggestion without changing the current mode.

    The dismissal is remembered only for the active session so the suggestion
    does not immediately reappear in the same session, but it never prevents
    future manual access.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        The unchanged reading-mode state with the suggestion cleared.
    """
    session = await _get_active_session(db, current_user)
    session.reading_mode_suggested = False

    await db.commit()
    await db.refresh(session)
    await invalidate_user_view(current_user.id)

    return ReadingModeResponse(
        bandwidth=session.reading_bandwidth,
        intent=session.reading_intent,
        source=session.reading_mode_source,
        suggested=session.reading_mode_suggested,
    )


@router.post("/api/v1/reading-mode/suggest")
@limiter.limit("60/minute")
async def suggest_reading_mode(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ReadingModeResponse:
    """Mark the active session as a candidate for the reading-mode quiz.

    Used by flows that detect low confidence or repeated mismatch (for example
    the Snooze correction flow) to offer the quiz without forcing it.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        The reading-mode state with the suggestion enabled.
    """
    session = await _get_active_session(db, current_user)
    session.reading_mode_suggested = True

    await db.commit()
    await db.refresh(session)
    await invalidate_user_view(current_user.id)

    return ReadingModeResponse(
        bandwidth=session.reading_bandwidth,
        intent=session.reading_intent,
        source=session.reading_mode_source,
        suggested=session.reading_mode_suggested,
    )
