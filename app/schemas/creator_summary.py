"""Schemas for the bounded personal creator summary API (issue #2028)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreatorSummaryItem(BaseModel):
    """Summary data for one creator identity in the batch response.

    ``canonical_creator_key`` is the stable provider + external-ID key from the
    #2036 creator identity contract (``creator:<external-person-id>``). It is
    never display-name based.
    """

    model_config = {"frozen": True}

    canonical_creator_key: str = Field(
        ...,
        description="Stable normalized creator key (e.g. ``creator:12345``).",
    )
    display_name: str = Field(
        ...,
        description="Human-readable creator name from confirmed issue metadata.",
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
    ratings_count: int = Field(
        default=0,
        ge=0,
        description="Number of distinct rated issues contributing to the headline average.",
    )
    read_unrated_count: int = Field(
        default=0,
        ge=0,
        description="Number of read-but-unrated owned issues attributed to this creator.",
    )
    upcoming_count: int = Field(
        default=0,
        ge=0,
        description="Number of unread owned issues already in the user's ComicPile "
        "attributed to this creator.",
    )


class CreatorSummaryCoverage(BaseModel):
    """Coverage state distinguishing complete from lower-bound statistics.

    ``*_complete`` is true only when every owned issue in that category carries
    confirmed usable creator metadata. Missing/unconfirmed metadata never
    counts as negative attribution evidence; it only makes the matching result
    explicitly partial.
    """

    model_config = {"frozen": True}

    rated_issues_total: int = Field(
        default=0,
        ge=0,
        description="Total owned issues with an effective rating.",
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


class CreatorSummariesResponse(BaseModel):
    """Response body for the batch creator summary API."""

    model_config = {"frozen": True}

    summaries: dict[str, CreatorSummaryItem] = Field(
        ...,
        description="Mapping from canonical creator key to summary data for every "
        "requested key visible in the authenticated user's library.",
    )
    coverage: CreatorSummaryCoverage = Field(
        ...,
        description="Coverage state distinguishing complete from lower-bound statistics.",
    )