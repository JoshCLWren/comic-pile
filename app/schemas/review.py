"""Review-related Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


ReviewText = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=2000,
        strip_whitespace=True,
    ),
]


class ReviewCreate(BaseModel):
    """Schema for creating a new review."""

    thread_id: int = Field(..., gt=0)
    rating: float = Field(..., ge=0.5, le=5.0, multiple_of=0.5)
    issue_number: str | None = Field(
        None,
        description="Issue number (if reviewing a specific issue)",
    )
    review_text: ReviewText | None = Field(
        None,
        description="Review text content",
    )


class ReviewUpdate(BaseModel):
    """Schema for updating an existing review."""

    rating: float | None = Field(None, ge=0.5, le=5.0, multiple_of=0.5)
    review_text: ReviewText | None = Field(
        None,
        description="Review text content",
    )


class ReviewResponse(BaseModel):
    """Schema for review response."""

    id: int
    user_id: int
    thread_id: int
    rating: float
    review_text: str | None
    issue_id: int | None
    issue_number: str | None
    thread_title: str
    thread_format: str
    created_at: datetime
    updated_at: datetime


class ReviewListResponse(BaseModel):
    """Schema for paginated review list response."""

    reviews: list[ReviewResponse]
    next_page_token: str | None = None
