"""Schemas for the bounded personal creator comparison API (issue #3091)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreatorComparisonRoleStat(BaseModel):
    """Role-specific statistics for a creator in comparison."""

    model_config = {"frozen": True}

    role: str = Field(..., description="The normalized role name.")
    issue_count: int = Field(
        ..., ge=0, description="Number of issues the creator held this role on."
    )
    average_rating: float | None = Field(
        default=None,
        description="Average rating for issues where the creator held this specific role.",
    )


class CreatorComparisonSeriesAggregate(BaseModel):
    """Strongest series/thread aggregate for a creator."""

    model_config = {"frozen": True}

    thread_id: int = Field(..., description="Local ComicPile thread ID.")
    thread_title: str = Field(..., description="Title of the series/thread.")
    issue_count: int = Field(
        ..., ge=0, description="Number of issues by this creator in this series."
    )
    average_rating: float | None = Field(
        default=None,
        description="Average rating for this creator's issues in this series.",
    )


class CreatorComparisonItem(BaseModel):
    """Comparison data for one creator identity."""

    model_config = {"frozen": True}

    canonical_creator_key: str = Field(
        ..., description="Stable normalized creator key (e.g. ``creator:12345``)."
    )
    display_name: str = Field(
        ..., description="Human-readable creator name from confirmed issue metadata."
    )
    normalized_roles: list[str] = Field(
        default_factory=list,
        description="Distinct roles seen for this creator across the user's issues.",
    )
    average_rating: float | None = Field(
        default=None,
        description="Average of the user's latest effective ratings across issues "
        "attributed to this creator with a headline-eligible role. ``null`` when no ratings.",
    )
    median_rating: float | None = Field(
        default=None,
        description="Median of the user's latest effective ratings across headline-eligible issues. "
        "``null`` when fewer than 1 rated issue.",
    )
    ratings_count: int = Field(
        default=0,
        ge=0,
        description="Number of distinct rated issues contributing to the headline average.",
    )
    rating_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Distribution of ratings (e.g. {'5': 3, '4': 2, '3': 1}).",
    )
    top_rating_rate: float | None = Field(
        default=None,
        description="Proportion of ratings at the top of ComicPile's 1-5 scale (5★). "
        "``null`` when no ratings.",
    )
    role_stats: list[CreatorComparisonRoleStat] = Field(
        default_factory=list,
        description="Breakdown of statistics per role.",
    )
    strongest_series: list[CreatorComparisonSeriesAggregate] = Field(
        default_factory=list,
        description="Top series/threads by issue count and average rating.",
    )
    unread_upcoming_count: int = Field(
        default=0,
        ge=0,
        description="Number of unread owned issues already in the user's ComicPile "
        "attributed to this creator.",
    )
    read_unrated_count: int = Field(
        default=0,
        ge=0,
        description="Number of read-but-unrated owned issues attributed to this creator.",
    )
    insufficient_data: bool = Field(
        default=False,
        description="True when the creator has fewer than 3 rated issues, making "
        "statistics less reliable.",
    )


class CreatorComparisonCoverage(BaseModel):
    """Coverage state distinguishing complete from lower-bound statistics across compared creators."""

    model_config = {"frozen": True}

    rated_issues_total: int = Field(
        default=0,
        ge=0,
        description="Total owned issues with an effective rating across all compared creators.",
    )
    rated_issues_with_creator_metadata: int = Field(
        default=0,
        ge=0,
        description="Rated owned issues with confirmed usable creator metadata.",
    )
    ratings_complete: bool = Field(
        default=True,
        description="True only when every owned rated issue has confirmed "
        "usable creator metadata.",
    )
    read_unrated_issues_total: int = Field(
        default=0,
        ge=0,
        description="Total owned read-but-unrated issues.",
    )
    read_unrated_issues_with_creator_metadata: int = Field(
        default=0,
        ge=0,
        description="Read-but-unrated owned issues with confirmed usable creator metadata.",
    )
    read_unrated_complete: bool = Field(
        default=True,
        description="True only when every owned read-but-unrated issue has "
        "confirmed usable creator metadata.",
    )
    unread_issues_total: int = Field(
        default=0,
        ge=0,
        description="Total owned unread issues.",
    )
    unread_issues_with_creator_metadata: int = Field(
        default=0,
        ge=0,
        description="Unread owned issues with confirmed usable creator metadata.",
    )
    upcoming_complete: bool = Field(
        default=True,
        description="True only when every owned unread issue considered by the "
        "library has confirmed usable creator metadata.",
    )


class CreatorComparisonResponse(BaseModel):
    """Response body for the batch creator comparison API."""

    model_config = {"frozen": True}

    comparisons: dict[str, CreatorComparisonItem] = Field(
        ...,
        description="Mapping from canonical creator key to comparison data for every "
        "requested key visible in the authenticated user's library.",
    )
    coverage: CreatorComparisonCoverage = Field(
        ..., description="Coverage state distinguishing complete from lower-bound statistics."
    )
    insufficient_data_keys: list[str] = Field(
        default_factory=list,
        description="Canonical keys of creators with insufficient data (fewer than 3 rated issues).",
    )


__all__ = [
    "CreatorComparisonResponse",
    "CreatorComparisonItem",
    "CreatorComparisonCoverage",
    "CreatorComparisonRoleStat",
    "CreatorComparisonSeriesAggregate",
]
