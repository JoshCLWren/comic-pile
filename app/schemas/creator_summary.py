"""Schemas for the creator summary API endpoint."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CreatorSummaryItem(BaseModel):
    """Summary data for one creator key in the batch response."""

    model_config = {"frozen=True"}

    canonical_creator_key: str = Field(
        ...,
        description="Stable normalized creator key (e.g. ``creator:writer:alan-moore``).",
    )
    display_name: str = Field(
        ...,
        description="Human-readable creator name.",
    )
    normalized_roles: list[str] = Field(
        default_factory=list,
        description="Roles seen for this creator across the user's issues (e.g. ``[\"writer\"]``).",
    )
    average_rating: Optional[float] = Field(
        default=None,
        description="Average rating across all rated issues attributed to this creator. ``null`` when no ratings.",
    )
    ratings_count: int = Field(
        default=0,
        ge=0,
        description="Number of rating contributions attributed to this creator.",
    )
    read_unrated_count: int = Field(
        default=0,
        ge=0,
        description="Number of read-but-unrated issues attributed to this creator.",
    )
    upcoming_count: int = Field(
        default=0,
        ge=0,
        description="Number of unread issues already in the user's ComicPile attributed to this creator.",
    )


class CreatorSummaryCoverage(BaseModel):
    """Coverage state for the three statistic categories, exposing whether counts are complete."""

    model_config = {"frozen=True"}

    rated_issues_total: int = Field(
        ge=0,
        description="Total number of rated issues in the user's owned library.",
    )
    rated_issues_with_creator_metadata: int = Field(
        ge=0,
        description="Number of rated issues that have confirmed usable creator metadata.",
    )
    ratings_complete: bool = Field(
        description="True only when every owned rated issue has confirmed usable creator metadata.",
    )
    read_unrated_issues_total: int = Field(
        ge=0,
        description="Total number of read-but-unrated issues in the user's owned library.",
    )
    read_unrated_issues_with_creator_metadata: int = Field(
        ge=0,
        description="Number of read-but-unrated issues that have confirmed usable creator metadata.",
    )
    read_unrated_complete: bool = Field(
        description="True only when every owned read-but-unrated issue has confirmed usable creator metadata.",
    )
    unread_issues_total: int = Field(
        ge=0,
        description="Total number of unread issues in the user's owned library.",
    )
    unread_issues_with_creator_metadata: int = Field(
        ge=0,
        description="Number of unread issues that have confirmed usable creator metadata.",
    )
    upcoming_complete: bool = Field(
        description="True only when every owned unread issue considered by the library has confirmed usable creator metadata.",
    )


class CreatorSummariesResponse(BaseModel):
    """Response body for the batch creator summary API."""

    model_config = {"frozen=True"}

    summaries: dict[str, CreatorSummaryItem] = Field(
        ...,
        description="Mapping from canonical creator key to summary data.",
    )
    coverage: CreatorSummaryCoverage = Field(
        ...,
        description="Coverage state distinguishing complete from lower-bound statistics.",
    )


class CreatorSummaryRequest(BaseModel):
    """Query parameters for the creator summary batch endpoint."""

    model_config = {"frozen=True"}

    keys: str = Field(
        ...,
        description="Comma-separated list of creator keys to summarize.",
    )