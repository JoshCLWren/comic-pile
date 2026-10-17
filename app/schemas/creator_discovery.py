"""Schemas for creator discovery views (issue #3093).

Discovery views surface useful patterns in user's creator ratings that they may
not think to search for manually, while keeping every result deterministic and
explainable.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class DiscoveryMode(str, Enum):
    """Supported creator discovery modes."""
    
    CONSISTENTLY_LOVED = "consistently_loved"
    POLARIZING = "polarizing" 
    MOST_READ = "most_read"
    HIGHEST_TOP_RATING_RATE = "highest_top_rating_rate"
    GREAT_AVERAGE_SMALL_SAMPLE = "great_average_small_sample"
    LOVED_WITH_UNREAD = "loved_with_unread"


class DiscoveryResultItem(BaseModel):
    """One row in a creator discovery collection.
    
    Each result shows the creator and the specific metrics that qualified them
    for this discovery mode, making the results explainable and transparent.
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
    
    # Core metrics that qualify the creator for this discovery mode
    average_rating: float | None = Field(
        default=None,
        description="Personal average rating across headline-eligible issues.",
    )
    ratings_count: int = Field(
        default=0,
        ge=0,
        description="Number of distinct rated issues contributing to the average.",
    )
    
    # Discovery-mode-specific qualifying metrics
    qualifying_metrics: dict[str, float | int | str] = Field(
        default_factory=dict,
        description="Specific metrics that qualified this creator for the discovery mode.",
    )
    
    # Additional context for explainability
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


class DiscoveryResponse(BaseModel):
    """Response body for a creator discovery endpoint."""

    model_config = {"frozen": True}

    mode: DiscoveryMode = Field(
        ...,
        description="The discovery mode being used.",
    )
    title: str = Field(
        ...,
        description="Human-readable title for this discovery mode.",
    )
    description: str = Field(
        ...,
        description="Explanation of what this discovery mode shows and how it works.",
    )
    items: list[DiscoveryResultItem] = Field(
        ...,
        description="Discovery results ordered by relevance for this mode.",
    )
    total: int = Field(
        ...,
        ge=0,
        description="Total number of creators matching the discovery criteria.",
    )
    limit: int = Field(
        ...,
        ge=1,
        le=50,
        description="Page size requested.",
    )
    offset: int = Field(
        ...,
        ge=0,
        description="Page offset requested.",
    )


class DiscoveryModesResponse(BaseModel):
    """Response for listing available discovery modes."""

    model_config = {"frozen": True}

    modes: list[dict[str, str]] = Field(
        ...,
        description="List of available discovery modes with metadata.",
    )