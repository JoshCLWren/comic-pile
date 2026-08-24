"""Pydantic schemas for manual session-mode changes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ModeBandwidth = Literal["light", "balanced", "deep"]
ModeIntentValue = Literal["balanced", "momentum", "familiar", "explore", "random"]


class ModeChangeRequest(BaseModel):
    """Schema for changing the active session mode.

    Allows explicitly changing the active session's bandwidth and/or intent
    without creating a second mode-state system.

    - Unspecified dimensions are not reset (preserve existing state).
    - Changed dimensions are marked with source ``manual`` and full confidence.
    - Invalid enum values fail safely (422 validation error).
    """

    model_config = {"extra": "forbid"}

    bandwidth: ModeBandwidth | None = Field(
        default=None,
        description="Active bandwidth for the session (light, balanced, or deep). "
        "When omitted, the current bandwidth is preserved.",
    )

    intent: ModeIntentValue | None = Field(
        default=None,
        description="Reading intent for the session (balanced, momentum, familiar, "
        "explore, or random). When omitted, the current intent is preserved.",
    )


class ModeChangeResponse(BaseModel):
    """Response containing the canonical updated mode state after a mode change.

    Returns the updated session mode state with all dimensions that were in effect,
    marked with their source and confidence semantics.
    """

    model_config = {"extra": "forbid"}

    bandwidth: str | None = Field(
        default=None,
        description="Current bandwidth (light/balanced/deep) for the session.",
    )

    intent: str | None = Field(
        default=None,
        description="Current reading intent for the session.",
    )

    source: str | None = Field(
        default=None,
        description="Source of the last mode change (manual, inferred, snooze, quiz).",
    )

    confidence: float | None = Field(
        default=None,
        description="Confidence associated with the last mode change.",
    )

    session_id: int = Field(
        description="ID of the session that was modified.",
    )

    updated_at: str = Field(
        description="ISO timestamp of when the mode was updated.",
    )
