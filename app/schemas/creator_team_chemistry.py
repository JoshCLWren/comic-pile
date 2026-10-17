"""Schemas for the bounded personal creator-team chemistry API (issue #3094)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.constants import MIN_SHARED_TEAM_SAMPLE


class CreatorTeamBaseline(BaseModel):
    """Baseline metrics for a single canonical creator."""

    model_config = {"frozen": True}

    creator_key: str = Field(..., description="Stable canonical creator key.")
    display_name: str = Field(..., description="Creator display name.")
    rated_issue_count: int = Field(..., ge=0, description="Rated issues in baseline.")
    average_rating: float | None = Field(
        default=None, description="Baseline average, or null."
    )


class CreatorTeamPair(BaseModel):
    """A ranked creator pair with shared chemistry metrics."""

    model_config = {"frozen": True}

    pair_key: str = Field(..., description="Stable unordered pair key.")
    creator_a: CreatorTeamBaseline = Field(..., description="First creator baseline.")
    creator_b: CreatorTeamBaseline = Field(..., description="Second creator baseline.")
    shared_rated_issue_count: int = Field(..., ge=0, description="Shared rated issues.")
    shared_average_rating: float | None = Field(
        default=None, description="Shared average, or null."
    )
    shared_rating_distribution: dict[str, int] = Field(
        default_factory=dict, description="Shared rating distribution."
    )
    shared_median_rating: float | None = Field(
        default=None, description="Shared median, or null."
    )
    difference_from_a_baseline: float | None = Field(
        default=None, description="Shared minus A baseline."
    )
    difference_from_b_baseline: float | None = Field(
        default=None, description="Shared minus B baseline."
    )
    shared_series: list[dict[str, object]] = Field(
        default_factory=list, description="Bounded series sample."
    )
    shared_issue_refs: list[dict[str, object]] = Field(
        default_factory=list, description="Bounded issue sample."
    )
    max_shared_issue_refs: int = Field(default=5, ge=1, description="Max issue refs.")


class CreatorTeamChemistryResponse(BaseModel):
    """Response payload for the creator team chemistry endpoint."""

    model_config = {"frozen": True}

    pairs: list[CreatorTeamPair] = Field(
        default_factory=list, description="Ranked pairs."
    )
    min_shared_team_sample: int = Field(
        default=MIN_SHARED_TEAM_SAMPLE, ge=1, description="Minimum shared sample."
    )
    pairs_total: int = Field(default=0, ge=0, description="Ranked pair count.")
    coverage: dict[str, object] = Field(
        default_factory=dict, description="Metadata coverage state."
    )
    insufficient_data_keys: list[str] = Field(
        default_factory=list, description="Unreliable baseline creator keys."
    )


__all__ = [
    "CreatorTeamBaseline",
    "CreatorTeamPair",
    "CreatorTeamChemistryResponse",
]
