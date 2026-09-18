"""Performance metric API endpoints.

Thin routing layer: authentication, request/response schema validation,
HTTP status mapping, and rate limiting. Business logic lives in
``app/services/performance_metric_service.py``; query construction lives in
``app/repositories/``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas import PerformanceMetricCreate, PerformanceMetricQuery, PerformanceMetricSummary
from app.schemas.performance_metric import PerformanceMetricComparison
from app.services import performance_metric_service


router = APIRouter(tags=["performance-metrics"])


@router.post(
    "/",
    description="Record a performance metric from a production request.",
    status_code=202,
)
async def record_metric(
    payload: PerformanceMetricCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Record a performance metric for the current request.

    Args:
        payload: The metric data to record.
        current_user: Authenticated user information.
        db: Database session.

    Returns:
        202 Accepted response.
    """
    metric_id = await performance_metric_service.record_request_metric(
        db,
        metric_type=payload.metric_type,
        response_time_ms=payload.response_time_ms,
        request_path=payload.request_path,
        deployment_id=payload.deployment_id,
        success=payload.success,
        user_id=current_user.id,
    )
    return JSONResponse(
        content={"id": metric_id, "status": "recorded"},
        status_code=202,
    )


@router.get(
    "/",
    description="Query performance metrics with optional filters.",
)
async def query_metrics(
    query: PerformanceMetricQuery = Depends(),
    db: AsyncSession = Depends(get_db),
) -> PerformanceMetricSummary:
    """Query performance metrics with optional filters.

    Args:
        query: Query parameters for filtering and pagination.
        db: Database session.

    Returns:
        Summary of performance metrics matching the filters.
    """
    data = await performance_metric_service.get_metrics_summary(
        db,
        metric_type=query.metric_type,
        deployment_id=query.deployment_id,
        days=query.days,
    )
    return PerformanceMetricSummary.model_validate(data)


@router.get(
    "/comparison",
    description="Get cold vs warm response time comparison for a metric type.",
)
async def cold_warm_comparison(
    metric_type: str | None = Query(None, description="Filter by metric type"),
    deployment_id: str | None = Query(
        None, description="Filter by deployment/commit identifier"
    ),
    db: AsyncSession = Depends(get_db),
) -> PerformanceMetricComparison:
    """Get cold vs warm response time comparison.

    Args:
        metric_type: Optional filter by metric type.
        deployment_id: Optional filter by deployment/commit identifier.
        db: Database session.

    Returns:
        Cold and warm stats including count, min, max, median, p95.
    """
    data = await performance_metric_service.get_cold_warm_comparison(
        db,
        metric_type=metric_type,
        deployment_id=deployment_id,
    )
    return PerformanceMetricComparison.model_validate(data)
