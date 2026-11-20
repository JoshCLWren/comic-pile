"""Performance metric service for orchestrating metric collection.

Services own business rules, transaction boundaries (commit/rollback),
and orchestration. Query construction lives in
``app/repositories/performance_metric_repository.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

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
    user_id: int | None = None,
) -> int:
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
        user_id: Optional user ID associated with the request.

    Returns:
        The id of the created PerformanceMetric record.
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
        user_id=user_id,
    )
    await db.flush()
    metric_id = metric.id
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return metric_id


async def get_metrics_summary(
    db: AsyncSession,
    *,
    metric_type: str | None = None,
    deployment_id: str | None = None,
    days: int | None = None,
) -> dict[str, object]:
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

    result = await performance_metric_repository.get_performance_metrics_summary(
        db,
        metric_type=metric_type,
        deployment_id=deployment_id,
        start_time=start_time,
        end_time=end_time,
    )
    return {
        "count": result["count"],
        "by_cold": result["by_cold"],
        "by_cold_stats": result["by_cold_stats"],
    }


async def get_cold_warm_comparison(
    db: AsyncSession,
    *,
    metric_type: str | None = None,
    deployment_id: str | None = None,
) -> dict[str, object]:
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

    by_cold_stats: dict[bool, dict[str, float | None]] = summary["by_cold_stats"]
    by_cold: dict[bool, int] = summary["by_cold"]
    cold_stats: dict[str, float | None] = by_cold_stats.get(True, {})
    warm_stats: dict[str, float | None] = by_cold_stats.get(False, {})

    return {
        "cold": {
            "count": by_cold.get(True, 0),
            **{k: v for k, v in cold_stats.items() if v is not None},
        },
        "warm": {
            "count": by_cold.get(False, 0),
            **{k: v for k, v in warm_stats.items() if v is not None},
        },
        "total": summary["count"],
    }
