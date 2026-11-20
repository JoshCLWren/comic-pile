"""Performance metric repository for query construction and persistence.

All SQLAlchemy access for the ``PerformanceMetric`` model family lives here.
Functions return ORM models or plain values; services own transactions.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.performance_metric import PerformanceMetric


async def create_performance_metric(
    db: AsyncSession,
    *,
    metric_type: str,
    cold: bool,
    response_time_ms: float,
    deployment_id: str | None = None,
    request_path: str | None = None,
    success: bool = True,
    user_id: int | None = None,
) -> PerformanceMetric:
    """Create and persist a new performance metric record.

    Args:
        db: Database session.
        metric_type: Type of metric (e.g. "initial_response", "shell_render",
            "auth_completion", "api_response", "queue_load").
        cold: Whether this was a cold-start request.
        response_time_ms: Response time in milliseconds.
        deployment_id: Deployment or commit identifier.
        request_path: The request path being measured.
        success: Whether the request succeeded.
        user_id: Optional user ID associated with the request.

    Returns:
        The created PerformanceMetric instance.
    """
    metric = PerformanceMetric(
        metric_type=metric_type,
        cold=cold,
        response_time_ms=response_time_ms,
        deployment_id=deployment_id,
        request_path=request_path,
        success=success,
        user_id=user_id,
    )
    db.add(metric)
    return metric


async def get_performance_metrics(
    db: AsyncSession,
    *,
    metric_type: str | None = None,
    cold: bool | None = None,
    deployment_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int | None = None,
) -> list[PerformanceMetric]:
    """Query performance metrics with optional filters.

    Args:
        db: Database session.
        metric_type: Filter by metric type.
        cold: Filter by cold/warm classification.
        deployment_id: Filter by deployment/commit identifier.
        start_time: Return metrics from this time onward.
        end_time: Return metrics up to this time.
        limit: Maximum number of results to return.

    Returns:
        List of PerformanceMetric instances ordered by timestamp descending.
    """
    query = select(PerformanceMetric)

    if metric_type is not None:
        query = query.where(PerformanceMetric.metric_type == metric_type)
    if cold is not None:
        query = query.where(PerformanceMetric.cold == cold)
    if deployment_id is not None:
        query = query.where(PerformanceMetric.deployment_id == deployment_id)
    if start_time is not None:
        query = query.where(PerformanceMetric.timestamp >= start_time)
    if end_time is not None:
        query = query.where(PerformanceMetric.timestamp <= end_time)

    query = query.order_by(PerformanceMetric.timestamp.desc())

    if limit is not None:
        query = query.limit(limit)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_performance_metrics_summary(
    db: AsyncSession,
    *,
    metric_type: str | None = None,
    deployment_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> dict[str, object]:
    """Get a summary of performance metrics including percentiles.

    Args:
        db: Database session.
        metric_type: Optional filter by metric type.
        deployment_id: Optional filter by deployment/commit identifier.
        start_time: Optional start time filter.
        end_time: Optional end time filter.

    Returns:
        Dict with count, min, max, median, p95 response times grouped by cold/warm.
    """
    base_query = select(PerformanceMetric)

    if metric_type is not None:
        base_query = base_query.where(PerformanceMetric.metric_type == metric_type)
    if deployment_id is not None:
        base_query = base_query.where(PerformanceMetric.deployment_id == deployment_id)
    if start_time is not None:
        base_query = base_query.where(PerformanceMetric.timestamp >= start_time)
    if end_time is not None:
        base_query = base_query.where(PerformanceMetric.timestamp <= end_time)

    # Aggregate from the filtered subquery so every aggregate column comes from
    # the filtered relation itself. Selecting from the base PerformanceMetric
    # entity alongside the subquery would add the original table to the FROM
    # clause, producing a Cartesian product that multiplies counts and corrupts
    # min/max/percentile results.
    base_subquery = base_query.subquery()

    # Count by cold/warm — aggregates only the filtered relation.
    count_query = select(
        base_subquery.c.cold,
        func.count(base_subquery.c.id).label("count"),
    ).select_from(base_subquery).group_by(base_subquery.c.cold)

    count_result = await db.execute(count_query)
    by_cold: dict[bool, int] = {
        cold: int(count) for cold, count in count_result.all()
    }

    # Response time stats by cold/warm — aggregates only the filtered relation.
    stats_query = select(
        base_subquery.c.cold,
        func.min(base_subquery.c.response_time_ms).label("min"),
        func.max(base_subquery.c.response_time_ms).label("max"),
        func.percentile_cont(0.5).within_group(
            base_subquery.c.response_time_ms
        ).label("median"),
        func.percentile_cont(0.95).within_group(
            base_subquery.c.response_time_ms
        ).label("p95"),
    ).select_from(base_subquery).group_by(base_subquery.c.cold)

    stats_result = await db.execute(stats_query)
    by_cold_stats: dict[bool, dict[str, float | None]] = {
        row.cold: {
            "min": float(row.min) if row.min is not None else None,
            "max": float(row.max) if row.max is not None else None,
            "median": float(row.median) if row.median is not None else None,
            "p95": float(row.p95) if row.p95 is not None else None,
        }
        for row in stats_result.all()
    }

    total = sum(by_cold.values())

    return {
        "count": total,
        "by_cold": by_cold,
        "by_cold_stats": by_cold_stats,
    }
