"""Schemas for the bounded personal creator discovery list (issue #2775)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.creator_summary import CreatorSummaryCoverage


class CreatorListItem(BaseModel):
    """One row in the bounded creator discovery collection.

    The row mirrors the headline rating semantics from ``#2028``/``#2037``:
    only effective ``rate`` events with a headline-eligible role feed
    ``ratings_count``/``average_rating`` and one issue counts at most once
    even when a creator has several roles on that issue.
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
        "attributed to this creator with a headline-eligible role. ``null`` when "
        "no headline-eligible ratings (explicit null handling for deterministic ordering).",
    )
    ratings_count: int = Field(
        default=0,
        ge=0,
        description="Number of distinct rated issues contributing to the headline average.",
    )


class CreatorListResponse(BaseModel):
    """Response body for the bounded personal creator list endpoint."""

    model_config = {"frozen": True}

    items: list[CreatorListItem] = Field(
        ...,
        description="Bounded, deterministically ordered page of creators with at least "
        "one rated issue for the authenticated user.",
    )
    total: int = Field(
        ...,
        ge=0,
        description="Total number of creators matching the filter before pagination.",
    )
    limit: int = Field(
        ...,
        ge=1,
        description="Page size requested.",
    )
    offset: int = Field(
        ...,
        ge=0,
        description="Page offset requested.",
    )
    coverage: CreatorSummaryCoverage = Field(
        ...,
        description="Coverage state distinguishing complete from lower-bound statistics.",
    )
