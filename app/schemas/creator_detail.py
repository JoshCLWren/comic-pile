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


class CreatorIssueInsight(BaseModel):
    """One individual issue extreme backing a creator highlight (issue #3092).

    Individual issue extremes are deliberately modeled separately from the
    aggregate series conclusions so a one-off rating is never presented as a
    creator's overall "best work".
    """

    model_config = {"frozen": True}

    issue_id: int = Field(..., description="Local ComicPile issue ID.")
    issue_number: str = Field(..., description="Issue number of the comic.")
    thread_id: int = Field(..., description="Local thread the issue belongs to.")
    thread_title: str = Field(..., description="Title of the containing thread.")
    effective_rating: float = Field(
        ...,
        description="Latest effective rating for this issue, one per issue.",
    )
    roles: list[str] = Field(
        ...,
        description="Sorted distinct roles the creator held on this issue.",
    )
    sort_key: str = Field(
        ...,
        description="Stable deterministic key for this issue extreme.",
    )


class CreatorSeriesInsight(BaseModel):
    """One series/run extreme backed by a minimum rated-issue sample (#3092).

    A series only qualifies as strongest/weakest/most-rated when it has at
    least :attr:`CreatorInsights.min_series_sample` rated issues and complete
    creator metadata, so a single 5★ issue cannot outrank a long loved run.
    """

    model_config = {"frozen": True}

    series_key: str = Field(
        ...,
        description="Stable series identity key (``thread:<thread_id>``).",
    )
    thread_id: int = Field(..., description="Local thread (series/run) id.")
    thread_title: str = Field(..., description="Current local thread title.")
    rated_issue_count: int = Field(
        ...,
        ge=0,
        description="Rated attributed issues backing this series insight.",
    )
    average_rating: float = Field(
        ...,
        description="Personal average over the series' rated issues.",
    )
    lowest_rating: float = Field(..., description="Lowest effective rating in the series.")
    highest_rating: float = Field(..., description="Highest effective rating in the series.")
    roles: list[str] = Field(
        ...,
        description="Sorted distinct roles the creator held in this series.",
    )
    metadata_complete: bool = Field(
        ...,
        description="Always true for a qualifying insight; incomplete series are excluded.",
    )
    sort_key: str = Field(..., description="Stable deterministic key for this series extreme.")


class CreatorInsights(BaseModel):
    """Evidence-backed strongest/weakest/most-read highlights (issue #3092).

    Every highlight links back to its supporting series or issues so a reader
    never has to trust an unexplained summary. Series conclusions require a
    minimum rated-issue sample and complete creator metadata; individual issue
    extremes are labeled separately from the aggregate series conclusions.

    The explanation for a missing series comparison names the real reason
    (issue #3946), and an individual issue never appears in both the highest
    and the lowest list.
    """

    min_series_sample: int = Field(
        ...,
        ge=1,
        description="Rated issues a series needs before it can be ranked as best/worst.",
    )
    series_sample_met: bool = Field(
        ...,
        description="True when at least one series meets the minimum rated-issue sample.",
    )
    series_message: str | None = Field(
        default=None,
        description="Plain-language explanation when no series comparison is available. "
        "It names the real reason: incomplete creator metadata, credits that do not "
        "count toward the average, or a genuinely thin rated-issue sample.",
    )
    excluded_incomplete_series_count: int = Field(
        default=0,
        ge=0,
        description="Series with attributed rated work excluded because their creator metadata "
        "is incomplete; a partial series is never presented as exhaustive evidence.",
    )
    individual_issue_limit: int = Field(
        ...,
        ge=0,
        description="Maximum number of individual issue extremes listed per direction.",
    )
    individual_issues_combined: bool = Field(
        default=False,
        description="True when the rated set is too small to separate into distinct highest "
        "and lowest lists. The UI then shows every rated issue once in a single list "
        "instead of repeating the same issues as both the best and the worst work.",
    )
    strongest_series: CreatorSeriesInsight | None = Field(
        default=None,
        description="Highest-average qualifying series, or null when the sample is too thin.",
    )
    weakest_series: CreatorSeriesInsight | None = Field(
        default=None,
        description="Lowest-average qualifying series, or null when the sample is too thin.",
    )
    most_rated_series: CreatorSeriesInsight | None = Field(
        default=None,
        description="Qualifying series with the most rated issues, or null when none qualify.",
    )
    highest_rated_issues: list[CreatorIssueInsight] = Field(
        default_factory=list,
        description="Top individual rated issues, distinct from aggregate series conclusions. "
        "Never overlaps with lowest_rated_issues.",
    )
    lowest_rated_issues: list[CreatorIssueInsight] = Field(
        default_factory=list,
        description="Bottom individual rated issues, distinct from aggregate series conclusions. "
        "Never overlaps with highest_rated_issues.",
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
    insights: CreatorInsights | None = Field(
        default=None,
        description="Evidence-backed strongest/weakest/most-read highlights (issue #3092). "
        "``null`` when the creator has no headline-eligible ratings.",
    )