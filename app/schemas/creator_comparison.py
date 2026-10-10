"""Schemas for the bounded personal creator comparison API (issue #3091).

Includes the bounded metric drilldown contracts (issue #3176): every
summary metric can be opened into its exact calculation and supporting
issue set, using the same shared aggregation semantics as the batch
comparison so summary and drilldown always reconcile.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.constants import MIN_RATED_ISSUES_PER_SERIES

#: Rating buckets the distribution drilldown accepts. These are exactly
#: the keys the summary rating distribution can emit on ComicPile's
#: 1-5 half-star scale, so a drilldown bucket always names a real
#: summary bucket.
RATING_BUCKETS: tuple[str, ...] = (
    "5",
    "4.5",
    "4",
    "3.5",
    "3",
    "2.5",
    "2",
    "1.5",
    "1",
)


class CreatorComparisonRoleStat(BaseModel):
    """Role-specific statistics for a creator in comparison."""

    model_config = {"frozen": True}

    role: str = Field(..., description="The normalized role name.")
    issue_count: int = Field(
        ..., ge=0, description="Number of issues the creator held this role on."
    )
    rated_issue_count: int = Field(
        ..., ge=0, description="Number of rated issues backing the average_rating for this role."
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
    rated_issue_count: int = Field(
        ...,
        ge=MIN_RATED_ISSUES_PER_SERIES,
        description="Number of rated issues backing average_rating. Series below "
        "the minimum rated sample are excluded from strongest_series entirely.",
    )
    average_rating: float = Field(
        ...,
        description="Average rating for this creator's rated issues in this series. "
        "Always present because only series meeting the minimum rated sample are returned.",
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
        description="Series ranked by rating strength, strongest first. Series with fewer "
        "than min_rated_issues_per_series rated issues are excluded.",
    )
    min_rated_issues_per_series: int = Field(
        default=MIN_RATED_ISSUES_PER_SERIES,
        ge=1,
        description="Minimum rated issues a series needs before strongest_series ranks it. "
        "Exposed so the UI can explain an empty list instead of silently hiding it.",
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


class CreatorDrilldownIssue(BaseModel):
    """One issue contributing to a metric drilldown evidence page."""

    model_config = {"frozen": True}

    issue_id: int = Field(..., description="Local ComicPile issue id.")
    issue_number: str = Field(
        ..., description="Reader-facing issue number as stored in ComicPile."
    )
    rating: float | None = Field(
        default=None,
        description="Latest effective rating for the issue, when the "
        "metric evidence consists of rated issues.",
    )
    role: str | None = Field(
        default=None,
        description="Creator role on this issue for the drilled metric.",
    )
    thread_id: int | None = Field(
        default=None, description="Local thread (series/run) id."
    )
    thread_title: str | None = Field(
        default=None, description="Series/run title for local context."
    )


class CreatorDrilldownRatingObservation(BaseModel):
    """One ranked rating observation in the median drilldown.

    The observation doubles as the supporting-issue row for the
    median metric, so the ranked evidence and the issue list are
    one bounded, paginated surface.
    """

    model_config = {"frozen": True}

    issue_id: int = Field(..., description="Local ComicPile issue id.")
    issue_number: str = Field(..., description="Reader-facing issue number.")
    rank: int = Field(
        ...,
        ge=1,
        description="1-based rank, strongest rating first.",
    )
    rating: float = Field(..., ge=1, le=5, description="Latest effective rating.")
    determines_median: bool = Field(
        default=False,
        description="True for the middle observation(s) that determine "
        "the median.",
    )
    role: str | None = Field(
        default=None, description="Creator's headline role on this issue."
    )
    thread_id: int | None = Field(
        default=None, description="Local thread (series/run) id."
    )
    thread_title: str | None = Field(
        default=None, description="Series/run title for local context."
    )


class CreatorDrilldownResponse(BaseModel):
    """Shared bounded evidence envelope for every metric drilldown.

    ``total_count`` is the size of the complete evidence set, so a
    client can always tell how much of the evidence the current page
    carries; ``next_cursor`` is null on the last page.
    """

    model_config = {"frozen": True}

    metric: str = Field(..., description="Drilldown metric identifier.")
    creator_key: str = Field(
        ..., description="Canonical creator key the evidence belongs to."
    )
    calculation: str = Field(
        ...,
        description="Human-readable formula that produces the visible "
        "summary metric from the stored evidence.",
    )
    total_count: int = Field(
        ...,
        ge=0,
        description="Total issues in the complete evidence set across "
        "all pages.",
    )
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor requesting the next evidence page; "
        "null on the last page.",
    )


class CreatorAverageDrilldownResponse(CreatorDrilldownResponse):
    """Evidence page for the average rating metric."""

    model_config = {"frozen": True}

    metric: Literal["average"] = "average"
    total_rated: int = Field(
        ..., ge=0, description="Rated issues contributing to the average."
    )
    total_points: float = Field(
        ..., ge=0, description="Sum of effective ratings behind the average."
    )
    issues: list[CreatorDrilldownIssue] = Field(
        default_factory=list, description="Bounded page of rated issues."
    )


class CreatorMedianDrilldownResponse(CreatorDrilldownResponse):
    """Evidence page for the median rating metric."""

    model_config = {"frozen": True}

    metric: Literal["median"] = "median"
    ratings_count: int = Field(
        ..., ge=0, description="Rated issues in the ranked sample."
    )
    median_rating: float | None = Field(
        default=None,
        description="Median of the ranked sample, matching the summary "
        "median exactly.",
    )
    sorted_ratings: list[CreatorDrilldownRatingObservation] = Field(
        default_factory=list,
        description="Bounded page of ranked observations, strongest first.",
    )


class CreatorDistributionDrilldownResponse(CreatorDrilldownResponse):
    """Evidence page for one rating-distribution bucket."""

    model_config = {"frozen": True}

    metric: Literal["distribution"] = "distribution"
    bucket: str = Field(..., description="Rating bucket key (e.g. ``4.5``).")
    bucket_count: int = Field(
        ..., ge=0, description="Rated issues with exactly this bucket rating."
    )
    total_rated: int = Field(
        ..., ge=0, description="Rated issues in the creator's headline sample."
    )
    issues: list[CreatorDrilldownIssue] = Field(
        default_factory=list, description="Bounded page of bucket issues."
    )


class CreatorFiveStarRateDrilldownResponse(CreatorDrilldownResponse):
    """Evidence page for the 5★ rate metric."""

    model_config = {"frozen": True}

    metric: Literal["5-star-rate"] = "5-star-rate"
    top_count: int = Field(..., ge=0, description="Rated issues at 5.0★.")
    rated_count: int = Field(
        ..., ge=0, description="Rated issues in the creator's headline sample."
    )
    issues: list[CreatorDrilldownIssue] = Field(
        default_factory=list, description="Bounded page of five-star issues."
    )


class CreatorRoleAverageDrilldownResponse(CreatorDrilldownResponse):
    """Evidence page for one role's average rating."""

    model_config = {"frozen": True}

    metric: Literal["role-average"] = "role-average"
    role: str = Field(..., description="The drilled creator role.")
    issue_count: int = Field(
        ..., ge=0, description="Total issues credited to the creator in this role."
    )
    rated_issue_count: int = Field(
        ..., ge=0, description="Credited issues with an effective rating."
    )
    average_rating: float | None = Field(
        default=None,
        description="Average effective rating across the rated credited "
        "issues, matching the summary role statistic.",
    )
    issues: list[CreatorDrilldownIssue] = Field(
        default_factory=list,
        description="Bounded page of rated issues credited in this role.",
    )


class CreatorSeriesAverageDrilldownResponse(CreatorDrilldownResponse):
    """Evidence page for one series' average rating."""

    model_config = {"frozen": True}

    metric: Literal["series-average"] = "series-average"
    thread_id: int = Field(..., description="Local thread (series/run) id.")
    thread_title: str = Field(..., description="Series/run title.")
    issue_count: int = Field(
        ..., ge=0, description="Total issues attributed to the creator here."
    )
    rated_issue_count: int = Field(
        ..., ge=0, description="Attributed issues with an effective rating."
    )
    average_rating: float | None = Field(
        default=None,
        description="Average effective rating across the rated attributed "
        "issues, matching the summary series aggregate.",
    )
    min_rated_issues_per_series: int = Field(
        ...,
        ge=1,
        description="Minimum rated issues before a series is ranked in "
        "strongest_series.",
    )
    issues: list[CreatorDrilldownIssue] = Field(
        default_factory=list,
        description="Bounded page of rated issues attributed in this series.",
    )


class CreatorReadWithoutRatingDrilldownResponse(CreatorDrilldownResponse):
    """Evidence page for the read-without-rating count.

    The per-issue cause classification does not exist yet (issue
    #3175), so ``classification_available`` is always false and the
    response says so explicitly instead of implying a known cause.
    """

    model_config = {"frozen": True}

    metric: Literal["read-without-rating"] = "read-without-rating"
    count: int = Field(
        ..., ge=0, description="Attributed issues marked read with no "
        "effective rate event."
    )
    classification_available: bool = Field(
        default=False,
        description="Always false until issue #3175 lands; per-issue "
        "missing-rating causes are not classified yet.",
    )
    issues: list[CreatorDrilldownIssue] = Field(
        default_factory=list,
        description="Bounded page of read-but-unrated attributed issues.",
    )


class CreatorUnreadDrilldownResponse(CreatorDrilldownResponse):
    """Evidence page for the unread/attributed-unread count."""

    model_config = {"frozen": True}

    metric: Literal["unread"] = "unread"
    count: int = Field(
        ..., ge=0, description="Attributed issues still unread in ComicPile."
    )
    issues: list[CreatorDrilldownIssue] = Field(
        default_factory=list,
        description="Bounded page of unread attributed issues.",
    )


__all__ = [
    "CreatorComparisonResponse",
    "CreatorComparisonItem",
    "CreatorComparisonCoverage",
    "CreatorComparisonRoleStat",
    "CreatorComparisonSeriesAggregate",
    "CreatorAverageDrilldownResponse",
    "CreatorDistributionDrilldownResponse",
    "CreatorDrilldownIssue",
    "CreatorDrilldownRatingObservation",
    "CreatorDrilldownResponse",
    "CreatorFiveStarRateDrilldownResponse",
    "CreatorMedianDrilldownResponse",
    "CreatorReadWithoutRatingDrilldownResponse",
    "CreatorRoleAverageDrilldownResponse",
    "CreatorSeriesAverageDrilldownResponse",
    "CreatorUnreadDrilldownResponse",
    "RATING_BUCKETS",
]
