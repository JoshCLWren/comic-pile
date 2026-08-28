"""Recommendation context Pydantic schemas for API validation."""

from __future__ import annotations

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
