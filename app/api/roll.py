"""Roll API routes."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Event, ReadingSession
from app.models.user import User
from app.services.recommendation_explanation import RecommendationExplanationProjection
from app.services.roll_service import RollService
from app.schemas import (
    ExplainableFactorResponse,
    OverrideRequest,
    RecommendationExplanationResponse,
    RollResponse,
)

router = APIRouter(tags=["roll"])


@router.post("/dismiss-pending", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_pending_roll(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear any pending thread for the current session.

    Args:
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.
    """
    service = RollService(db)
    await service.execute_dismiss_pending(current_user.id)


@router.post("/override", response_model=RollResponse)
async def override_roll(
    request: OverrideRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RollResponse:
    """Manually select a thread.

    Args:
        request: Override request containing thread_id.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        RollResponse with selected thread.

    Raises:
        HTTPException: If thread not found.
    """
    return await RollService(db).execute_override(
        thread_id=request.thread_id, current_user=current_user
    )


@router.get(
    "/events/{event_id}/recommendation-explanation",
    response_model=RecommendationExplanationResponse,
)
async def get_roll_recommendation_explanation(
    event_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RecommendationExplanationResponse:
    """Return human-readable explanations for a historical roll event.

    Derives explanations solely from the recommendation context persisted at
    roll decision time, never recomputing scores from current mutable state.
    Unknown or absent context degrades gracefully to an empty explanation list.

    Args:
        event_id: Identifier of the roll event to explain.
        current_user: Authenticated owner of the session that generated the event.
        db: Async database session.

    Returns:
        RecommendationExplanationResponse carrying the event identifier and
        ordered list of human-readable explanation factors.

    Raises:
        HTTPException 404: When the event does not exist or does not belong
            to the current user's session.
        HTTPException 422: When the event type is not ``"roll"``.
    """
    result = await db.execute(
        select(Event, ReadingSession.user_id)
        .join(ReadingSession, Event.session_id == ReadingSession.id)
        .where(Event.id == event_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )
    event, session_user_id = row
    if session_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )
    if event.type != "roll":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Event {event_id} is not a roll event",
        )

    context: dict[str, Any] | None = None
    if hasattr(event, "recommendation_context") and event.recommendation_context is not None:
        raw = event.recommendation_context
        if isinstance(raw, dict):
            context = raw
        elif isinstance(raw, str):
            try:
                context = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                context = None

    factors = RecommendationExplanationProjection.project_recommendation_context(
        context=context,
        selection_method=event.selection_method,
    )

    return RecommendationExplanationResponse(
        event_id=event_id,
        factors=[
            ExplainableFactorResponse(
                code=f.code,
                label=f.label,
                detail=f.detail,
            )
            for f in factors
        ],
    )
