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
        description="Number of issues the creator held this role on.",
    )
    average_rating: float | None = Field(
        default=None,
        description="Average rating for issues where the creator held this specific role.",
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