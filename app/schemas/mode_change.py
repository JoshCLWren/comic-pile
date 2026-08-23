"""Pydantic schemas for manual session-mode changes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, validator


class ModeChangeRequest(BaseModel):
    """Schema for changing the active session mode.

    Allows explicitly changing the active session's bandwidth (die size) and/or
    intent without creating a second mode-state system.

    - Unspecified dimensions are not reset (preserve existing state).
    - Changed dimensions are marked with source `manual` and appropriate confidence.
    - Invalid enum values fail safely (422 validation error).
    """

    model_config = {"extra": "forbid"}

    bandwidth: int | None = Field(
        default=None,
        description="Die size / bandwidth for the active session. "
        "Must be a valid dice ladder value (4, 6, 8, 10, 12, 20, 30, 50, 100). "
        "When not specified, the current bandwidth is preserved.",
        ge=4,
        le=100,
    )

    intent: str | None = Field(
        default=None,
        description="Intent of the mode change. When set to 'random', activates "
        "the Phase 3 contextual-weight bypass (unweighted control behavior). "
        "When not specified, the current intent is preserved.",
    )

    @validator("bandwidth")
    def validate_bandwidth_die_size(cls, v: int | None) -> int | None:
        """Validate that bandwidth is a valid dice ladder value."""
        if v is None:
            return v
        valid_sizes = [4, 6, 8, 10, 12, 20, 30, 50, 100]
        if v not in valid_sizes:
            raise ValueError(
                f"Invalid bandwidth die size: {v}. "
                f"Must be one of: {valid_sizes}"
            )
        return v


class ModeChangeResponse(BaseModel):
    """Response containing the canonical updated mode state after a mode change.

    Returns the updated session mode state with all dimensions that were in effect,
    marked with their source and confidence semantics.
    """

    model_config = {"extra": "forbid"}

    bandwidth: int | None = Field(
        default=None,
        description="Current bandwidth (die size) setting for the session.",
    )

    intent: str | None = Field(
        default=None,
        description="Current intent setting for the session.",
    )

    source: str | None = Field(
        default=None,
        description="Source of the last mode change (manual, system, inferred).",
    )

    confidence: float | None = Field(
        default=None,
        description="Confidence semantics associated with the last mode change.",
    )

    session_id: int = Field(
        default=...,
        description="ID of the session that was modified.",
    )

    updated_at: str = Field(
        default=...,
        description="ISO timestamp of when the mode was updated.",
    )


class ModeChangeHistoryEvent(BaseModel):
    """Schema for a mode-change event recorded in the event log."""

    model_config = {"extra": "forbid"}

    type: str = Field(
        default="mode_change",
        description="Event type identifier.",
    )

    session_id: int = Field(
        description="ID of the session affected.",
    )

    bandwidth: int | None = Field(
        default=None,
        description="Bandwidth (die size) after the change, or None if unchanged.",
    )

    intent: str | None = Field(
        default=None,
        description="Intent after the change, or None if unchanged.",
    )

    source: str | None = Field(
        default=None,
        description="Source of the mode change (manual, system, inferred).",
    )

    confidence: float | None = Field(
        default=None,
        description="Confidence semantics of the mode change.",
    )

    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO timestamp of the event.",
    )