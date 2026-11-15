"""Reading-mode API endpoints.

Exposes the two-question reading-mode quiz results and manual mode-selector
entries. Both flows write only to the active session and record the source
(``quiz`` or ``manual``) so the rest of the app can distinguish them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.middleware import limiter
from app.models.user import User
from app.services.reading_mode import ReadingModeService, get_reading_mode_service
from app.services.reading_quiz import QuizResolutionError, ReadingModeSource

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


class ReadingModeResponse(BaseModel):
    """Current reading-mode state for the active session."""

    bandwidth: str | None
    intent: str | None
    source: str | None
    suggested: bool


@router.get("/api/v1/reading-mode")
@limiter.limit("200/minute")
async def get_reading_mode(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ReadingModeService, Depends(get_reading_mode_service)],
) -> ReadingModeResponse:
    """Return the active session's current reading mode.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        service: Reading mode service dependency.

    Returns:
        The current reading-mode state.
    """
    data = await service.get_reading_mode(current_user)
    return ReadingModeResponse(**data)


@router.post("/api/v1/reading-mode")
@limiter.limit("60/minute")
async def set_reading_mode(
    request: Request,
    payload: ReadingModeSetRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ReadingModeService, Depends(get_reading_mode_service)],
) -> ReadingModeResponse:
    """Set the active session reading mode.

    Args:
        request: FastAPI request object for rate limiting.
        payload: The reading-mode set request.
        current_user: The authenticated user making the request.
        service: Reading mode service dependency.

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
        data = await service.set_reading_mode(
            current_user,
            bandwidth=payload.bandwidth,
            intent=payload.intent,
            answers=payload.answers,
            source=payload.source,
        )
    except (QuizResolutionError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return ReadingModeResponse(**data)


@router.post("/api/v1/reading-mode/dismiss-suggestion")
@limiter.limit("60/minute")
async def dismiss_reading_mode_suggestion(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ReadingModeService, Depends(get_reading_mode_service)],
) -> ReadingModeResponse:
    """Dismiss the reading-mode suggestion without changing the current mode.

    The dismissal is remembered only for the active session so the suggestion
    does not immediately reappear in the same session, but it never prevents
    future manual access.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        service: Reading mode service dependency.

    Returns:
        The unchanged reading-mode state with the suggestion cleared.
    """
    data = await service.dismiss_suggestion(current_user)
    return ReadingModeResponse(**data)


@router.post("/api/v1/reading-mode/suggest")
@limiter.limit("60/minute")
async def suggest_reading_mode(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ReadingModeService, Depends(get_reading_mode_service)],
) -> ReadingModeResponse:
    """Mark the active session as a candidate for the reading-mode quiz.

    Used by flows that detect low confidence or repeated mismatch (for example
    the Snooze correction flow) to offer the quiz without forcing it.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        service: Reading mode service dependency.

    Returns:
        The reading-mode state with the suggestion enabled.
    """
    data = await service.suggest_reading_mode(current_user)
    return ReadingModeResponse(**data)