"""Recommendation-quality diagnostics API endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services import recommendation_diagnostics as diagnostics_service
from app.schemas.recommendation_diagnostics import RecommendationDiagnosticsResponse

router = APIRouter(tags=["recommendations"])


@router.get(
    "/v1/recommendations/diagnostics",
    response_model=RecommendationDiagnosticsResponse,
    summary="Recommendation-quality diagnostics summary",
    description=(
        "Bounded, read-only recommendation-quality summary for the current user. "
        "This is a diagnostics endpoint and never runs during the normal Roll "
        "bootstrap path."
    ),
)
async def get_recommendation_diagnostics(
    range_start: datetime | None = Query(
        None, description="Inclusive lower bound (ISO 8601). Defaults to 30 days ago."
    ),
    range_end: datetime | None = Query(
        None, description="Exclusive upper bound (ISO 8601). Defaults to now."
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecommendationDiagnosticsResponse:
    """Get recommendation-quality diagnostics for the authenticated user.

    Args:
        range_start: Optional inclusive lower time bound.
        range_end: Optional exclusive upper time bound.
        current_user: The authenticated user making the request.
        db: The database session for querying decision history.

    Returns:
        A bounded, user-scoped :class:`RecommendationDiagnosticsResponse`.
    """
    resolved_start, resolved_end = diagnostics_service.resolve_diagnostics_range(
        range_start, range_end
    )
    return await diagnostics_service.compute_recommendation_diagnostics(
        db,
        user_id=current_user.id,
        range_start=resolved_start,
        range_end=resolved_end,
    )
