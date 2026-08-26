"""Pydantic schemas for process-local traffic metrics snapshots."""

from pydantic import BaseModel, Field


class RouteTrafficCounter(BaseModel):
    """One aggregated (method, route template, status class) tally."""

    method: str = Field(..., description="HTTP method, e.g. GET.")
    route: str = Field(..., description="Routed path template, e.g. /api/v1/threads/{thread_id}.")
    status_class: str = Field(..., description="Response status class, e.g. 2xx or 4xx.")
    count: int = Field(..., ge=1, description="Requests observed since process start.")


class TrafficMetricsSnapshot(BaseModel):
    """Process-local traffic counters for one serverless instance.

    Counters are monotonic within a process lifetime, so a collector can
    reconstruct fleet-wide totals by keeping the maximum count per key across
    polls of the same ``instance_id``.
    """

    instance_id: str = Field(..., description="Stable identifier for this process instance.")
    counters: list[RouteTrafficCounter] = Field(
        default_factory=list,
        description="Aggregated request tallies sorted deterministically.",
    )
