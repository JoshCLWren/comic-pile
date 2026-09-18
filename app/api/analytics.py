"""Analytics API endpoints for comic reading metrics."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.analytics import AnalyticsMetricsResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(tags=["analytics"])


@router.get("/analytics/metrics", response_model=AnalyticsMetricsResponse)
async def get_metrics(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AnalyticsMetricsResponse:
    """Get reading metrics and analytics for the current user.

    Args:
        current_user: The authenticated user making the request.
        db: The database session for querying data.

    Returns:
        Typed analytics payload covering thread counts, completion rate,
        average session length, recent sessions, event distribution, and
        top-rated threads.
    """
    service = AnalyticsService(db)
    return await service.get_metrics(current_user.id)
