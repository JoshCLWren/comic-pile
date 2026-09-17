"""Performance metric service for orchestrating metric collection.

Services own business rules, transaction boundaries (commit/rollback),
and orchestration. Query construction lives in
``app/repositories/performance_metric_repository.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.performance_metric import PerformanceMetric
from app.repositories import performance_metric_repository
from app.startup_diagnostics import next_request_snapshot


async def record_request_metric(
    db: AsyncSession,
    *,
    metric_type: str,
    response_time_ms: float,
    request_path: str | None = None,
    deployment_id: str | None = None,
    success: bool = True,
) -> PerformanceMetric:
    """Record a performance metric for the current request.

    Extracts cold/warm classification from the request snapshot and
    persists the metric to the database.

    Args:
        db: Database session.
        metric_type: Type of metric being recorded.
        response_time_ms: Measured response time in milliseconds.
        request_path: The request path being measured.
        deployment_id: Deployment or commit identifier.
        success: Whether the request succeeded.

    Returns:
        The created PerformanceMetric instance.
    """
    snapshot = next_request_snapshot()
    cold = snapshot.cold

    metric = await performance_metric_repository.create_performance_metric(
        db,
        metric_type=metric_type,
        cold=cold,
        response_time_ms=response_time_ms,
        deployment_id=deployment_id,
        request_path=request_path,
        success=success,
    )
    await db.flush()
    return metric


async def get_metrics_summary(
    db: AsyncSession,
    *,
    metric_type: str | None = None,
    deployment_id: str | None = None,
    days: int | None = None,
) -> dict:
    """Get a summary of performance metrics.

    Args:
        db: Database session.
        metric_type: Optional filter by metric type.
        deployment_id: Optional filter by deployment/commit identifier.
        days: If provided, only include metrics from the last N days.

    Returns:
        Summary dict with count, cold/warm breakdown, and response time percentiles.
    """
    start_time = None
    end_time = None
    if days is not None:
        end_time = datetime.now(UTC)
        start_time = datetime.now(UTC) - timedelta(days=days)

    return await performance_metric_repository.get_performance_metrics_summary(
        db,
        metric_type=metric_type,
        deployment_id=deployment_id,
        start_time=start_time,
        end_time=end_time,
    )


async def get_cold_warm_comparison(
    db: AsyncSession,
    *,
    metric_type: str | None = None,
    deployment_id: str | None = None,
) -> dict:
    """Get cold vs warm response time comparison for a metric type.

    Args:
        db: Database session.
        metric_type: Optional filter by metric type.
        deployment_id: Optional filter by deployment/commit identifier.

    Returns:
        Dict with cold and warm stats including count, min, max, median, p95.
    """
    summary = await performance_metric_repository.get_performance_metrics_summary(
        db,
        metric_type=metric_type,
        deployment_id=deployment_id,
    )

    cold_stats = summary.get("by_cold_stats", {}).get(True, {})
    warm_stats = summary.get("by_cold_stats", {}).get(False, {})

    return {
        "cold": {
            "count": summary.get("by_cold", {}).get(True, 0),
            **{k: v for k, v in cold_stats.items() if v is not None},
        },
        "warm": {
            "count": summary.get("by_cold", {}).get(False, 0),
            **{k: v for k, v in warm_stats.items() if v is not None},
        },
        "total": summary.get("count", 0),
    }
