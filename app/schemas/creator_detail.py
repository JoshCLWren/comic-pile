"""Schemas for the bounded personal creator detail API (issue #2037)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreatorRoleStats(BaseModel):
    """Role-specific statistics for a creator."""

    model_config = {"frozen": True}

    role: str = Field(..., description="Specific creator role (e.g., 'writer', 'artist').")
    average_rating: float | None = Field(
        default=None,
        description="Average rating for this role across the creator's credited issues.",
    )
    rated_count: int = Field(
        default=0,
        ge=0,
        description="Number of rated issues for this role.",
    )
    upcoming_count: int = Field(
        default=0,
        ge=0,
        description="Number of unread issues for this role.",
    )


class RatedIssue(BaseModel):
    """A rated issue attributed to this creator."""

    model_config = {"frozen": True}

    thread_id: int = Field(..., description="ComicPile thread ID.")
    thread_title: str = Field(..., description="Thread/series title.")
    issue_number: str = Field(..., description="Issue number.")
    creator_roles: list[str] = Field(..., description="Creator's roles on this issue.")
    effective_rating: float = Field(..., description="User's rating for this issue.")
    rated_at: str | None = Field(
        default=None,
        description="ISO timestamp when this rating was applied.",
    )


class UpcomingIssue(BaseModel):
    """An upcoming/unread issue attributed to this creator."""

    model_config = {"frozen": True}

    thread_id: int = Field(..., description="ComicPile thread ID.")
    thread_title: str = Field(..., description="Thread/series title.")
    issue_number: str = Field(..., description="Issue number.")
    creator_roles: list[str] = Field(..., description="Creator's roles on this issue.")
    queue_position: int = Field(..., description="Position in user's ComicPile queue.")


class ReadUnratedIssue(BaseModel):
    """A read but unrated issue attributed to this creator."""

    model_config = {"frozen": True}

    thread_id: int = Field(..., description="ComicPile thread ID.")
    thread_title: str = Field(..., description="Thread/series title.")
    issue_number: str = Field(..., description="Issue number.")
    creator_roles: list[str] = Field(..., description="Creator's roles on this issue.")
    read_at: str | None = Field(
        default=None,
        description="ISO timestamp when this issue was marked as read.",
    )


class CreatorDetailResponse(BaseModel):
    """Response body for the creator detail API."""

    model_config = {"frozen": True}

    display_name: str = Field(..., description="Human-readable creator name.")
    average_rating: float | None = Field(
        default=None,
        description="Average rating across all headline-eligible credited issues.",
    )
    ratings_count: int = Field(
        default=0,
        ge=0,
        description="Number of rated issues contributing to the average.",
    )
    read_unrated_count: int = Field(
        default=0,
        ge=0,
        description="Number of read-but-unrated issues attributed to this creator.",
    )
    upcoming_count: int = Field(
        default=0,
        ge=0,
        description="Number of unread issues attributed to this creator.",
    )
    ratings_complete: bool = Field(
        default=True,
        description="True only when every owned rated issue has confirmed creator metadata.",
    )
    upcoming_complete: bool = Field(
        default=True,
        description="True only when every owned unread issue has confirmed creator metadata.",
    )
    role_stats: list[CreatorRoleStats] = Field(
        default_factory=list,
        description="Role-specific statistics when meaningful.",
    )
    rated_issues: list[RatedIssue] = Field(
        default_factory=list,
        description="Rated issues attributed to this creator, in descending rating order.",
    )
    upcoming_issues: list[UpcomingIssue] = Field(
        default_factory=list,
        description="Upcoming issues in ComicPile queue order.",
    )
    read_unrated_issues: list[ReadUnratedIssue] = Field(
        default_factory=list,
        description="Read but unrated issues, in read order.",
    )
    page_token: str | None = Field(
        default=None,
        description="Token for fetching the next page of results.",
    )


class CreatorDetailCoverage(BaseModel):
    """Coverage state for creator detail pagination."""

    model_config = {"frozen": True}

    rated_issues_total: int = Field(
        default=0,
        ge=0,
        description="Total rated issues available for this creator.",
    )
    upcoming_issues_total: int = Field(
        default=0,
        ge=0,
        description="Total upcoming issues available for this creator.",
    )
    read_unrated_issues_total: int = Field(
        default=0,
        ge=0,
        description="Total read but unrated issues available for this creator.",
    )
