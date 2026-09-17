"""Performance metric service for orchestrating metric collection."""

from __future__ import annotations

import time
from collections.abc import MutableMapping

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status

from app.repositories import performance_metric_repository
from app.startup_diagnostics import (
    next_request_snapshot,
    reset_startup_diagnostics_for_test,
)
from app.database import get_db, AsyncSessionLocal


class PerformanceMetricService:
    """Service layer for performance metric collection and querying."""

    def __init__(self) -> None:
        self._cold_threshold_ms = 2000  # Requests slower than 2s are considered "cold" by default

    def set_cold_threshold(self, threshold_ms: int) -> None:
        """Set the cold-request threshold in milliseconds.

        Requests with response time above this threshold are classified as cold.
        """
        self._cold_threshold_ms = threshold_ms

    async def record_request_metric(
        self,
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

        async with get_db() as db:
            metric = await performance_metric_repository.create_performance_metric(
                db,
                metric_type=metric_type,
                cold=cold,
                response_time_ms=response_time_ms,
                deployment_id=deployment_id,
                request_path=request_path,
                success=success,
            )
            return metric

    async def record_current_metric(self, metric_type: str, request_path: str | None = None) -> dict:
        """Record a metric using the current request's timing info.

        Convenience method that captures the response time from the
        request state and records it.

        Args:
            metric_type: Type of metric being recorded.
            request_path: The request path being measured.

        Returns:
            The created PerformanceMetric as a dict.
        """
        snapshot = next_request_snapshot()
        # Try to get response time from request state
        response_time_ms = getattr(snapshot, "response_time_ms", None)

        async with get_db() as db:
            from app.models.performance_metric import PerformanceMetric

            deployment_id = getattr(snapshot, "deployment_id", None)

            metric = PerformanceMetric(
                metric_type=metric_type,
                cold=snapshot.cold,
                response_time_ms=response_time_ms or 0.0,
                deployment_id=deployment_id,
                request_path=request_path,
                success=True,
            )
            db.add(metric)
            await db.flush()
            return {
                "id": metric.id,
                "timestamp": metric.timestamp,
                "metric_type": metric.metric_type,
                "cold": metric.cold,
                "response_time_ms": metric.response_time_ms,
                "deployment_id": metric.deployment_id,
                "request_path": metric.request_path,
                "success": metric.success,
            }

    async def get_metrics_summary(
        self,
        *,
        metric_type: str | None = None,
        deployment_id: str | None = None,
        days: int | None = None,
    ) -> dict:
        """Get a summary of performance metrics.

        Args:
            metric_type: Optional filter by metric type.
            deployment_id: Optional filter by deployment/commit identifier.
            days: If provided, only include metrics from the last N days.

        Returns:
            Summary dict with count, cold/warm breakdown, and response time percentiles.
        """
        async with get_db() as db:
            from datetime import datetime as _datetime

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
        self,
        *,
        metric_type: str | None = None,
        deployment_id: str | None = None,
    ) -> dict:
        """Get cold vs warm response time comparison for a metric type.

        Args:
            metric_type: Optional filter by metric type.
            deployment_id: Optional filter by deployment/commit identifier.

        Returns:
            Dict with cold and warm stats including count, min, max, median, p95.
        """
        async with get_db() as db:
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