"""Pydantic schemas for performance metric request/response validation."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PerformanceMetricCreate(BaseModel):
    """Schema for creating a performance metric record.

    Args:
        metric_type: Type of metric (e.g. "initial_response", "shell_render",
            "auth_completion", "api_response", "queue_load").
        response_time_ms: Response time in milliseconds.
        request_path: The request path being measured (optional).
        deployment_id: Deployment or commit identifier (optional).
        success: Whether the request succeeded (default True).
    """

    metric_type: str = Field(..., min_length=1, description="Type of metric being recorded")
    response_time_ms: float = Field(..., ge=0, description="Response time in milliseconds")
    request_path: str | None = Field(
        None, max_length=500, description="The request path being measured"
    )
    deployment_id: str | None = Field(
        None, max_length=255, description="Deployment or commit identifier"
    )
    success: bool = Field(True, description="Whether the request succeeded")


class PerformanceMetricQuery(BaseModel):
    """Schema for querying performance metrics.

    Args:
        metric_type: Optional filter by metric type.
        cold: Optional filter by cold/warm classification.
        deployment_id: Optional filter by deployment/commit identifier.
        start_time: Optional start time filter (ISO datetime).
        end_time: Optional end time filter (ISO datetime).
        limit: Optional maximum number of results.
    """

    metric_type: str | None = Field(
        None, min_length=1, description="Optional filter by metric type"
    )
    cold: bool | None = Field(None, description="Optional filter by cold/warm classification")
    deployment_id: str | None = Field(
        None, max_length=255, description="Optional filter by deployment/commit identifier"
    )
    start_time: datetime | None = Field(
        None, description="Optional start time filter (ISO datetime)"
    )
    end_time: datetime | None = Field(
        None, description="Optional end time filter (ISO datetime)"
    )
    days: int | None = Field(
        None, ge=1, description="Only include metrics from the last N days"
    )
    limit: int | None = Field(
        None, ge=1, le=1000, description="Optional maximum number of results"
    )


class PerformanceMetricSummary(BaseModel):
    """Schema for performance metric summary response."""

    count: int = Field(..., description="Total number of metrics")
    by_cold: dict[bool, int] = Field(
        ...,
        description="Count of metrics grouped by cold/warm classification",
    )
    by_cold_stats: dict[bool, dict[str, float | None]] = Field(
        ...,
        description="Response time stats (min, max, median, p95) grouped by cold/warm",
    )


class PerformanceMetricComparison(BaseModel):
    """Schema for cold vs warm comparison response."""

    cold: dict[str, object] = Field(
        ...,
        description="Cold statistics: count, min, max, median, p95",
    )
    warm: dict[str, object] = Field(
        ...,
        description="Warm statistics: count, min, max, median, p95",
    )
    total: int = Field(
        ...,
        description="Total number of metrics",
    )