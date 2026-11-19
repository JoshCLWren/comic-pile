"""Schemas for explainable personal taste-discovery views (issue #3093).

Every view is descriptive personal analytics derived from the authenticated
user's own latest effective ratings and confirmed creator credits. Each entry
carries the complete metric block plus the explicit reasons that qualified it,
so the UI can always show *why* a creator appeared rather than an unexplained
ranking. No field exists to express global quality, causation, or statistical
significance, and no provider or LLM request participates.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.constants import MAX_DISCOVERY_ENTRIES


class CreatorDiscoveryMode(StrEnum):
    """The fixed, deterministic set of personal taste-discovery views.

    Ordering in this enum is the canonical display order of the views.
    """

    CONSISTENTLY_LOVED = "consistently_loved"
    POLARIZING = "polarizing"
    MOST_READ = "most_read"
    HIGHEST_TOP_RATING_RATE = "highest_top_rating_rate"
    GREAT_AVERAGE_SMALL_SAMPLE = "great_average_small_sample"
    LOVED_WITH_UNREAD = "loved_with_unread"
    MOVED_OVER_TIME = "moved_over_time"


class CreatorDiscoveryReason(BaseModel):
    """One deterministic rule that qualified a creator for a view.

    ``value`` is the observed metric and ``threshold`` is the fixed rule the
    metric had to satisfy. ``comparison`` is one of ``gte``, ``lte``, ``gt``,
    ``lt`` so the UI can render the relationship without parsing prose.
    """

    model_config = {"frozen": True}

    metric: str = Field(..., description="Machine key of the qualifying metric.")
    label: str = Field(..., description="Human-readable metric name for UI copy.")
    value: float = Field(..., description="Observed value of the metric.")
    threshold: float = Field(..., description="Threshold the value had to satisfy.")
    comparison: str = Field(..., description="One of gte, lte, gt, lt.")


class CreatorDiscoveryEntry(BaseModel):
    """One canonical creator inside a discovery view with supporting metrics."""

    model_config = {"frozen": True}

    canonical_creator_key: str = Field(
        ..., description="Stable normalized creator key (e.g. ``creator:12345``)."
    )
    display_name: str = Field(
        ..., description="Human-readable creator name from confirmed issue metadata."
    )
    normalized_roles: list[str] = Field(
        default_factory=list,
        description="Distinct confirmed roles seen for this creator.",
    )
    rated_issue_count: int = Field(
        ..., ge=0, description="Headline-eligible rated issues contributing to the metrics."
    )
    average_rating: float | None = Field(
        default=None, description="Personal average across the rated sample."
    )
    median_rating: float | None = Field(
        default=None, description="Personal median across the rated sample."
    )
    rating_stddev: float | None = Field(
        default=None,
        description="Population standard deviation across the rated sample, or null when unrated.",
    )
    rating_spread: float | None = Field(
        default=None, description="Highest minus lowest effective rating, or null when unrated."
    )
    min_rating: float | None = Field(default=None, description="Lowest effective rating.")
    max_rating: float | None = Field(default=None, description="Highest effective rating.")
    top_rating_rate: float | None = Field(
        default=None,
        description="Proportion of ratings at the top of the scale (0.0-1.0).",
    )
    top_rating_count: int = Field(
        default=0, ge=0, description="Count of ratings at the top of the scale."
    )
    unread_issue_count: int = Field(
        default=0, ge=0, description="Attributed unread owned issues for this creator."
    )
    read_unrated_issue_count: int = Field(
        default=0, ge=0, description="Attributed read-but-unrated owned issues."
    )
    trend_direction: str | None = Field(
        default=None,
        description="``warmed`` or ``cooled`` for the trend view, otherwise null.",
    )
    earlier_average_rating: float | None = Field(
        default=None, description="Average of the earlier half of a trend-eligible history."
    )
    recent_average_rating: float | None = Field(
        default=None, description="Average of the recent half of a trend-eligible history."
    )
    trend_delta: float | None = Field(
        default=None, description="Recent average minus earlier average for the trend view."
    )
    trend_sample_count: int = Field(
        default=0,
        ge=0,
        description="Rated issues carrying a timestamp that supported a trend, else 0.",
    )
    reasons: list[CreatorDiscoveryReason] = Field(
        default_factory=list,
        description="Every deterministic rule that qualified this creator for this view.",
    )


class CreatorDiscoveryView(BaseModel):
    """One bounded taste-discovery view and its qualifying creators."""

    model_config = {"frozen": True}

    mode: CreatorDiscoveryMode = Field(..., description="Stable view identifier.")
    title: str = Field(..., description="Short human-readable view title.")
    description: str = Field(
        ..., description="Deterministic explanation of what qualifies a creator."
    )
    min_sample: int = Field(
        ge=0, description="Minimum rated sample the view requires (0 = no floor)."
    )
    total: int = Field(ge=0, description="Qualifying creators before bounded truncation.")
    truncated: bool = Field(
        description="True when more creators qualified than the bounded response returns."
    )
    max_entries: int = Field(ge=1, description="Bounding constant applied to entries.")
    entries: list[CreatorDiscoveryEntry] = Field(default_factory=list)


class CreatorDiscoveryCoverage(BaseModel):
    """Explicit metadata-coverage state for the discovery aggregation."""

    model_config = {"frozen": True}

    rated_issues_total: int = Field(ge=0, description="Rated issues in the library.")
    rated_issues_with_creator_metadata: int = Field(
        ge=0, description="Rated issues carrying at least one usable confirmed credit."
    )
    ratings_complete: bool = Field(
        description="True only when every rated issue carries confirmed creator metadata."
    )


class CreatorDiscoveryResponse(BaseModel):
    """Response body for the bounded personal taste-discovery endpoint."""

    model_config = {"frozen": True}

    views: list[CreatorDiscoveryView] = Field(
        default_factory=list,
        description="One entry per view in canonical order, including empty views.",
    )
    coverage: CreatorDiscoveryCoverage = Field(
        ..., description="Metadata-coverage state distinguishing complete from lower bounds."
    )
    minimum_reliable_sample: int = Field(
        ge=1, description="The canonical personal-reliability rated-sample floor."
    )
    max_entries_per_view: int = Field(ge=1, description="Bounding constant applied per view.")


__all__ = [
    "MAX_DISCOVERY_ENTRIES",
    "CreatorDiscoveryCoverage",
    "CreatorDiscoveryEntry",
    "CreatorDiscoveryMode",
    "CreatorDiscoveryReason",
    "CreatorDiscoveryResponse",
    "CreatorDiscoveryView",
]
