"""Recommendation context Pydantic schemas for API validation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CandidateFactor(BaseModel):
    """Factor breakdown for a single candidate."""

    candidate_id: int
    factors: list[str] = Field(default_factory=list)
    weight: float = Field(..., ge=0.0, description="Final combined weight after caps")
    effort_minutes: float | None = None
    effort_band: str | None = None
    effort_source: str | None = None
    effort_confidence: float | None = None
    effort_sample_count: int | None = None


class RecommendationContextResponse(BaseModel):
    """Schema for returning recommendation context data."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    schema_version: int
    intent: str
    intent_source: str
    intent_confidence: float
    bandwidth: str | None = None
    bandwidth_source: str | None = None
    bandwidth_confidence: float | None = None
    candidate_factors: list[CandidateFactor] | None = None
    final_weight: float | None = None
    random_bypass: bool
    balanced_neutrality: bool
    effort_minutes: float | None = None
    effort_band: str | None = None
    effort_source: str | None = None
    effort_confidence: float | None = None
    effort_sample_count: int | None = None
    algorithm_version: str | None = None
    control_mode: str | None = None


class RecommendationContextCreate(BaseModel):
    """Schema for creating recommendation context."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=2, ge=1)
    intent: Literal["momentum", "familiar", "explore", "random", "balanced"]
    intent_source: str = Field(..., min_length=1, max_length=30)
    intent_confidence: float = Field(..., ge=0.0, le=1.0)
    bandwidth: Literal["light", "balanced", "deep"] | None = None
    bandwidth_source: str | None = Field(default=None, max_length=30)
    bandwidth_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_factors: list[CandidateFactor] | None = None
    final_weight: float | None = Field(default=None, ge=0.0)
    random_bypass: bool = False
    balanced_neutrality: bool = False
    effort_minutes: float | None = None
    effort_band: str | None = None
    effort_source: str | None = None
    effort_confidence: float | None = None
    effort_sample_count: int | None = None
    algorithm_version: str | None = Field(default=None, max_length=50)
    control_mode: str | None = Field(default=None, max_length=20)


class RollingRecommendationContext(BaseModel):
    """Versioned recommendation context snapshot captured at roll decision time.

    This schema captures the bounded candidate pool and selection context
    that existed when a roll was made, enabling later analysis to explain not
    only what the reader did, but what ComicPile knew and what candidate set
    it chose from at that moment.

    This is instrumentation only - does not change candidate ordering,
    random-selection probability, dice behavior, queue movement, or snooze semantics.
    """

    model_config = ConfigDict(from_attributes=True)

    schema_version: int = Field(default=1, ge=1, description="Version of the context schema")
    algorithm_version: str = Field(
        default="legacy",
        description="Canonical algorithm version identifier at decision time",
    )
    control_mode: str | None = Field(
        default=None,
        description="Active control mode (contextual or legacy) at decision time",
    )
    die_size: int = Field(..., gt=0, description="Current die size at roll time")
    selected_queue_position: int = Field(..., ge=1, description="Selected thread queue position at roll time")
    bounded_candidate_ids: list[int] = Field(
        default_factory=list,
        description="Bounded candidate thread IDs in exact selection order",
    )
    selected_index: int = Field(..., ge=0, description="Selected candidate index/result")
    selection_method: str = Field(
        ..., description="Selection method (random, momentum, legacy_forced, override, etc.)"
    )
    session_timezone: str | None = Field(
        default=None, description="Session timezone if available from browser"
    )
    local_hour: int | None = Field(
        default=None, ge=0, le=23, description="Local hour (0-23) derived from session timezone"
    )
    selected_thread_last_rating: float | None = Field(
        default=None, description="Selected thread last rating as seen at decision time"
    )
    selected_thread_last_activity_at: datetime | None = Field(
        default=None, description="Selected thread last activity timestamp as seen at decision time"
    )
    effort_estimate: str | None = Field(
        default=None, max_length=50, description="Explicitly known effort estimate if later work added it"
    )
