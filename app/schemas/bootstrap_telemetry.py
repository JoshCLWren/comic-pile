"""Pydantic schemas for bootstrap alias telemetry snapshots."""

from pydantic import BaseModel, Field


class BootstrapAliasCounterSchema(BaseModel):
    """One aggregated bootstrap alias tally."""

    alias: str = Field(..., description="Bootstrap alias: legacy, v1, or v2.")
    web_origin: bool = Field(..., description="True if request looked like a browser client.")
    status_class: str = Field(..., description="Response status class, e.g. 2xx.")
    count: int = Field(..., ge=0, description="Number of observed hits.")


class BootstrapAliasSnapshotSchema(BaseModel):
    """Process-local bootstrap alias counters."""

    counters: list[BootstrapAliasCounterSchema] = Field(
        default_factory=list,
        description="Aggregated counts per (alias, web_origin, status class).",
    )
