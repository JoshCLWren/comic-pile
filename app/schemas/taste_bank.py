"""Schemas for the Taste Bank API and internal taste inference results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TasteFeatureResponse(BaseModel):
    """One normalized taste feature with inferred state from Taste Bank."""

    signal_type: Literal["creator", "character", "team", "publisher", "era"]
    stable_key: str
    display_name: str
    role: str | None = None
    inferred_affinity: float = Field(description="Estimated preference strength; positive = aligned, negative = opposed, 0 = neutral")
    confidence: float = Field(description="How reliable this signal is; 0.0 = too sparse, 1.0 = very confident")
    evidence_count: int = Field(description="Total observations supporting this signal")
    distinct_threads_count: int = Field(description="Number of distinct threads contributing evidence")
    distinct_runs_count: int = Field(description="Number of distinct sessions contributing evidence")
    user_verdict: Literal["confirmed", "sometimes", "rejected"] | None = Field(
        description="Explicit user verdict when set; overrides inferred classification"
    )
    last_observed_at: str | None = None


class TasteBankSignalResponse(BaseModel):
    """Full TasteBank signal with all derived properties."""

    id: int
    user_id: int
    signal_type: Literal["creator", "character", "team", "publisher", "era"]
    stable_key: str
    display_name: str
    inferred_affinity: float
    evidence_count: int
    distinct_threads_count: int
    distinct_runs_count: int
    confidence: float
    user_verdict: Literal["confirmed", "sometimes", "rejected"] | None
    last_observed_at: str | None = None
    prompt_suppressed: bool = False


class TasteBankSummaryResponse(BaseModel):
    """Summary of a user's complete inferred Taste Bank."""

    signals: list[TasteBankSignalResponse]
    total_signals: int
    high_confidence_count: int = Field(description="Signals with confidence >= 0.7")
    explicit_verdict_count: int = Field(description="Signals with a non-null user verdict")


class TasteBankRebuildResponse(BaseModel):
    """Response after a taste bank rebuild."""

    signals_rebuilt: int
    signals_count: int


class TasteSignalVerdictUpdate(BaseModel):
    """Request body for applying or updating a user verdict on a taste signal."""

    verdict: Literal["confirmed", "sometimes", "rejected", "suppress"] = Field(
        description="Explicit user verdict: confirmed (liked), sometimes (mixed), rejected (disliked), suppress (no prompts)"
    )