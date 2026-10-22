"""Pydantic schemas for Roll bootstrap route telemetry snapshots (issue #2718)."""

from typing import Literal

from pydantic import BaseModel, Field

BootstrapAlias = Literal["unversioned", "v1", "v2"]
BootstrapClientClass = Literal["web", "external", "unknown"]


class BootstrapTrafficCounter(BaseModel):
    """One aggregated bootstrap tally keyed by alias, client class, and status.

    Only derived aggregates are stored: never request headers, URLs, user
    identities, or payloads. This keeps the counters safe to expose to
    authenticated operators while still supporting the future 7-day
    zero-web-origin deletion gate for the legacy aliases.
    """

    alias: BootstrapAlias = Field(..., description="Bootstrap route alias: unversioned, v1, v2.")
    client_class: BootstrapClientClass = Field(
        ..., description="Derived client origin class: web, external, or unknown."
    )
    status_class: str = Field(..., description="Response status class, e.g. 2xx or 4xx.")
    count: int = Field(..., ge=1, description="Requests observed since process start.")
    database_queries_sum: int = Field(
        default=0, ge=0, description="Sum of per-request database query counts."
    )
    database_queries_max: int = Field(
        default=0, ge=0, description="Maximum per-request database query count."
    )
    payload_bytes_sum: int = Field(
        default=0, ge=0, description="Sum of response payload byte counts."
    )
    payload_bytes_max: int = Field(
        default=0, ge=0, description="Maximum response payload byte count."
    )


class BootstrapMetricsSnapshot(BaseModel):
    """Process-local bootstrap telemetry for one serverless instance.

    Counters are monotonic within a process lifetime; a collector
    reconstructs fleet-wide totals by keeping the maximum count per key
    across polls of the same ``instance_id``.
    """

    instance_id: str = Field(..., description="Stable identifier for this process instance.")
    counters: list[BootstrapTrafficCounter] = Field(
        default_factory=list,
        description="Aggregated bootstrap tallies sorted deterministically.",
    )
