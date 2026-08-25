"""Pydantic schemas for recommendation-quality diagnostics responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EffortBandOutcome(BaseModel):
    """Recommendation outcomes bucketed by effort band (die size)."""

    model_config = ConfigDict(extra="forbid")

    die: int = Field(..., description="Die size that represents the effort band")
    band: Literal["low", "medium", "high"] = Field(
        ..., description="Coarse effort band derived from the die size"
    )
    rolls: int = Field(..., ge=0, description="Number of roll events in this band")
    accepted: int = Field(
        ..., ge=0, description="Rolls whose thread was later rated in range"
    )
    snoozed: int = Field(
        ..., ge=0, description="Rolls whose thread was later snoozed in range"
    )
    acceptance_rate: float = Field(
        ..., ge=0.0, le=1.0, description="accepted / rolls (0.0 when no rolls)"
    )
    snooze_rate: float = Field(
        ..., ge=0.0, le=1.0, description="snoozed / rolls (0.0 when no rolls)"
    )


class ControlModeGroup(BaseModel):
    """One recommendation-quality grouping by control mode and algorithm version."""

    model_config = ConfigDict(extra="forbid")

    algorithm_version: str = Field(
        ..., description="Canonical algorithm version attributed to this group"
    )
    control_mode: str = Field(
        ...,
        description=(
            "Distinguishable control/intent class: contextual_auto, explicit_correction, "
            "blocked_recovery, or legacy"
        ),
    )
    rolls: int = Field(..., ge=0)
    accepted_rolls: int = Field(..., ge=0)
    snoozed_rolls: int = Field(..., ge=0)
    acceptance_rate: float = Field(..., ge=0.0, le=1.0)
    snooze_rate: float = Field(..., ge=0.0, le=1.0)


class CoverageInfo(BaseModel):
    """Honest labeling of data completeness for the requested range."""

    model_config = ConfigDict(extra="forbid")

    instrumented_event_count: int = Field(
        ..., ge=0, description="Events carrying a selection_method (full context)"
    )
    legacy_event_count: int = Field(
        ..., ge=0, description="Events without selection_method (pre-instrumentation)"
    )
    partial_coverage: bool = Field(
        ..., description="True when legacy events are mixed into the range"
    )
    note: str = Field(
        ..., description="Human-readable explanation of coverage limitations"
    )


class RecommendationDiagnosticsResponse(BaseModel):
    """Bounded, read-only recommendation-quality summary for one user."""

    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(..., description="Owner of the summarized data")
    range_start: datetime = Field(..., description="Inclusive lower bound of the range")
    range_end: datetime = Field(..., description="Exclusive upper bound of the range")
    active_algorithm_version: str = Field(
        ..., description="Algorithm version currently active for this user"
    )
    active_control_mode: str = Field(
        ..., description="Control mode currently active for this user"
    )
    total_sessions: int = Field(..., ge=0)
    total_rolls: int = Field(..., ge=0)
    total_rates: int = Field(..., ge=0)
    total_snoozes: int = Field(..., ge=0)
    first_roll_adoption_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Sessions where the first roll was accepted"
    )
    snoozes_per_completed_read: float = Field(
        ..., ge=0.0, description="total_snoozes / total_rates (0.0 when no reads)"
    )
    max_consecutive_snoozes_before_acceptance: int = Field(
        ..., ge=0, description="Longest snooze run before any acceptance in a session"
    )
    avg_consecutive_snoozes_before_acceptance: float = Field(
        ..., ge=0.0, description="Mean snooze run before acceptance (0.0 when none)"
    )
    avg_time_to_acceptance_seconds: float | None = Field(
        ..., description="Mean session-start to first acceptance (None when none)"
    )
    mode_corrections: int = Field(
        ..., ge=0, description="Explicit manual/override launch-mode corrections"
    )
    rating_average: float | None = Field(
        ..., description="Mean rating across rated sessions (None when none)"
    )
    rating_distribution: dict[str, int] = Field(
        default_factory=dict, description="Rating histogram by integer bucket"
    )
    effort_band_outcomes: list[EffortBandOutcome] = Field(default_factory=list)
    groups_by_control_mode: list[ControlModeGroup] = Field(default_factory=list)
    coverage: CoverageInfo = Field(..., description="Coverage/legacy labeling for the range")
