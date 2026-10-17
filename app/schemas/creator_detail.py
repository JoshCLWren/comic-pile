"""Schemas for the bounded personal creator detail API (issue #2037)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.creator_summary import CreatorSummaryCoverage, CreatorSummaryItem


class CreatorRoleStat(BaseModel):
    """Statistics for a specific role for a creator."""

    role: str = Field(..., description="The normalized role name.")
    issue_count: int = Field(
        ...,
        ge=0,
        description="Number of distinct issues the creator held this role on (includes rated, unrated, and upcoming).",
    )
    rated_issue_count: int = Field(
        ...,
        ge=0,
        description="Number of those issues that have an effective rating and contributed to average_rating.",
    )
    average_rating: float | None = Field(
        default=None,
        description="Average rating for issues where the creator held this specific role (computed over rated_issue_count issues).",
    )


class CreatorIssueRow(BaseModel):
    """Detail for a specific issue attributed to the creator."""

    issue_id: int = Field(..., description="Local ComicPile issue ID.")
    issue_number: str = Field(..., description="Issue number of the comic.")
    thread_id: int = Field(..., description="Local ComicPile thread ID.")
    thread_title: str = Field(..., description="Title of the containing thread.")
    status: str = Field(..., description="Read/unread status.")
    roles: list[str] = Field(
        ...,
        description="Roles the creator held on this specific issue.",
    )
    effective_rating: float | None = Field(
        default=None,
        description="The latest effective rating for this issue, if any.",
    )
    rating_timestamp: datetime | None = Field(
        default=None,
        description="Timestamp of the effective rating event, if any.",
    )
    sort_key: str = Field(
        ...,
        description="Deterministic local ordering information for the UI.",
    )


class CreatorRatingBucket(BaseModel):
    """One half-star bucket in a creator's rating distribution."""

    model_config = {"frozen": True}

    rating: float = Field(
        ...,
        description="Bucket center on the product's real half-star scale (0.5–5.0).",
    )
    count: int = Field(
        ...,
        ge=0,
        description="Number of issues whose effective rating falls in this bucket.",
    )


class CreatorRatingDistribution(BaseModel):
    """Distribution, median, range, mean, and sample strength for one creator."""

    model_config = {"frozen": True}

    buckets: list[CreatorRatingBucket] = Field(
        ...,
        description="Half-star buckets from 0.5 to 5.0, always a complete fixed "
        "shape with explicit zero counts.",
    )
    sample_count: int = Field(
        ...,
        ge=0,
        description="Number of distinct rated issues contributing (at most one per issue).",
    )
    mean_rating: float = Field(
        ...,
        description="Mean of the latest effective ratings across contributing issues.",
    )
    median_rating: float = Field(
        ...,
        description="Median of the latest effective ratings across contributing issues.",
    )
    min_rating: float = Field(
        ...,
        description="Minimum effective rating observed for this creator.",
    )
    max_rating: float = Field(
        ...,
        description="Maximum effective rating observed for this creator.",
    )


class CreatorSeriesGroup(BaseModel):
    """Series/run-level aggregate of one creator's attributed rated work.

    Grouping identity is the stable local ComicPile thread id, never the
    display title: two distinct threads that happen to share a title stay in
    separate groups. Every aggregate is computed over the creator's complete
    attributed work for that thread, so the same group key always carries the
    same numbers regardless of which page of issue rows was requested.
    """

    series_key: str = Field(
        ...,
        description="Stable series identity key (``thread:<thread_id>``).",
    )
    thread_id: int = Field(
        ...,
        description="Local ComicPile thread (series/run) id used as the group identity.",
    )
    thread_title: str = Field(
        ...,
        description="Current local thread title. Display only; never a grouping identity.",
    )
    rated_issue_count: int = Field(
        ...,
        ge=0,
        description="Attributed issues in this thread with an effective rating. "
        "Equals the number of rows the drill-down can return for this group.",
    )
    average_rating: float | None = Field(
        default=None,
        description="Personal average over this group's rated issues, or null when none are rated.",
    )
    lowest_rating: float | None = Field(
        default=None,
        description="Lowest effective rating in this group, or null when none are rated.",
    )
    highest_rating: float | None = Field(
        default=None,
        description="Highest effective rating in this group, or null when none are rated.",
    )
    roles: list[str] = Field(
        ...,
        description="Sorted distinct roles the creator held in this thread.",
    )
    unread_issue_count: int = Field(
        ...,
        ge=0,
        description="Attributed unread issues of this creator still in this thread. "
        "Includes an unread issue that is also already rated, matching the "
        "existing upcoming semantics.",
    )
    read_unrated_issue_count: int = Field(
        ...,
        ge=0,
        description="Attributed issues in this thread that were read but never rated.",
    )
    metadata_complete: bool = Field(
        ...,
        description="False when some issues in this thread still lack confirmed creator "
        "metadata, making this group's counts lower bounds.",
    )
    sort_key: str = Field(
        ...,
        description="Stable final tie-breaker for the deterministic group ordering "
        "(most-rated first, then title, then this key).",
    )


class CreatorSeriesIssueListResponse(BaseModel):
    """Bounded drill-down of the issues supporting one creator series group."""

    series_key: str = Field(..., description="Stable series identity key echoed back.")
    thread_id: int = Field(..., description="Local ComicPile thread id.")
    thread_title: str = Field(..., description="Current local thread title.")
    roles: list[str] = Field(
        ...,
        description="Sorted distinct roles the creator held in this thread.",
    )
    rated_issue_count: int = Field(
        ...,
        ge=0,
        description="Total attributed rated issues backing this group.",
    )
    average_rating: float | None = Field(
        default=None,
        description="Personal average over the group's rated issues.",
    )
    lowest_rating: float | None = Field(
        default=None,
        description="Lowest effective rating in the group, or null when none are rated.",
    )
    highest_rating: float | None = Field(
        default=None,
        description="Highest effective rating in the group, or null when none are rated.",
    )
    metadata_complete: bool = Field(
        ...,
        description="False when some issues in this thread still lack confirmed creator "
        "metadata, making this group's counts lower bounds.",
    )
    issues: list[CreatorIssueRow] = Field(
        default_factory=list,
        description="Bounded page of supporting rated issues, recent-first.",
    )
    total: int = Field(..., ge=0, description="Total supporting rated issues in the group.")
    limit: int = Field(..., ge=1, description="Echoed page size.")
    offset: int = Field(..., ge=0, description="Echoed page offset.")
    next_cursor: str | None = Field(
        default=None,
        description="Cursor for paginating a long drill-down, null when exhausted.",
    )


class CreatorInsightIssue(BaseModel):
    """One individual rated issue surfaced by creator insights (issue #3092).

    Individual issue extremes are deliberately not aggregate series
    conclusions: a single 5-star issue may be shown, but it is always carried
    with its stable thread context so the UI can label it as an individual
    issue and drill into the supporting thread instead of implying the
    creator's "best work".
    """

    model_config = {"frozen": True}

    issue_id: int = Field(..., description="Local ComicPile issue id.")
    thread_id: int = Field(
        ...,
        description="Local ComicPile thread (series/run) id containing the issue.",
    )
    thread_title: str = Field(
        ...,
        description="Current local thread title. Display only; never a grouping identity.",
    )
    rating: float = Field(
        ...,
        description="Latest effective personal rating for this individual issue.",
    )


class CreatorInsights(BaseModel):
    """Strongest and weakest work analysis for one creator detail page (#3092).

    Series strongest/weakest/most-rated labels require a minimum rated-issue
    sample (``min_sample_threshold``) so a single high-rated issue cannot
    automatically outweigh a consistently loved longer run. Every selection is
    deterministic: series averages tie-break by the stable thread id and
    individual issue extremes tie-break by the stable issue id, so a tie never
    resolves by input order.

    Individual issue extremes live in ``highest_rated_issue`` and
    ``lowest_rated_issue`` and are never presented as aggregate series
    conclusions. When no series meets the minimum sample,
    ``has_sufficient_data`` is false, the series fields stay null, and the
    ordinary creator data is still returned.
    """

    model_config = {"frozen": True}

    has_sufficient_data: bool = Field(
        ...,
        description="True when at least one series meets the minimum rated-issue "
        "sample threshold, so strongest/weakest series conclusions are meaningful. "
        "False means the series comparison is intentionally withheld, not that the "
        "creator has no data.",
    )
    min_sample_threshold: int = Field(
        ...,
        ge=1,
        description="Minimum rated issues a series needs before it can be named the "
        "strongest, weakest, or most-rated series.",
    )
    highest_rated_series: CreatorSeriesGroup | None = Field(
        default=None,
        description="Qualified series with the highest personal average, or null when "
        "no series meets the minimum sample.",
    )
    lowest_rated_series: CreatorSeriesGroup | None = Field(
        default=None,
        description="Qualified series with the lowest personal average, or null when "
        "no series meets the minimum sample.",
    )
    most_rated_series: CreatorSeriesGroup | None = Field(
        default=None,
        description="Qualified series with the largest rated sample, or null when "
        "no series meets the minimum sample.",
    )
    highest_rated_issue: CreatorInsightIssue | None = Field(
        default=None,
        description="Single highest-rated individual issue, shown separately from "
        "aggregate series conclusions. Null when the creator has no attributable "
        "rated issues.",
    )
    lowest_rated_issue: CreatorInsightIssue | None = Field(
        default=None,
        description="Single lowest-rated individual issue, shown separately from "
        "aggregate series conclusions. Null when the creator has no attributable "
        "rated issues.",
    )


class CreatorDetailResponse(BaseModel):
    """Full detail response for a single creator identity."""

    summary: CreatorSummaryItem = Field(
        ...,
        description="The headline summary for the creator (from #2028).",
    )
    coverage: CreatorSummaryCoverage = Field(
        ...,
        description="Metadata coverage state (from #2028).",
    )
    role_stats: list[CreatorRoleStat] = Field(
        default_factory=list,
        description="Breakdown of statistics per role.",
    )
    series_groups: list[CreatorSeriesGroup] = Field(
        default_factory=list,
        description="Bounded page of series/run-level aggregates, most-rated first.",
    )
    series_groups_total: int = Field(
        default=0,
        ge=0,
        description="Total series/run groups with attributed rated work for this creator.",
    )
    series_groups_complete: bool = Field(
        default=True,
        description="False when this page does not contain every series/run group, so the "
        "listed groups are a lower bound until further pages are loaded.",
    )
    rated_issues: list[CreatorIssueRow] = Field(
        default_factory=list,
        description="Bounded list of rated issues, recent-first.",
    )
    read_unrated_issues: list[CreatorIssueRow] = Field(
        default_factory=list,
        description="Bounded list of read-but-unrated issues.",
    )
    upcoming_issues: list[CreatorIssueRow] = Field(
        default_factory=list,
        description="Bounded list of upcoming unread issues.",
    )
    next_cursor: str | None = Field(
        default=None,
        description="Cursor for paginating long collections.",
    )
    rating_distribution: CreatorRatingDistribution | None = Field(
        default=None,
        description="Headline-eligible rating distribution (half-star buckets, median, "
        "range, mean, sample count). ``null`` when the creator has no eligible ratings.",
    )
    insights: CreatorInsights = Field(
        ...,
        description="Strongest and weakest work analysis for this creator. Always "
        "present: ``has_sufficient_data`` is false when no series meets the "
        "minimum sample, and the ordinary creator data is still returned.",
    )
