"""Thread-related Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, Field


class ThreadCreate(BaseModel):
    """Schema for creating a new thread."""

    title: str = Field(..., min_length=1)
    format: str = Field(..., min_length=1)
    issues_remaining: int = Field(..., ge=0)
    notes: str | None = None
    is_test: bool = False


class ThreadUpdate(BaseModel):
    """Schema for updating a thread."""

    title: str | None = Field(None, min_length=1)
    format: str | None = Field(None, min_length=1)
    issues_remaining: int | None = Field(None, ge=0)
    notes: str | None = None
    is_test: bool | None = None


class ThreadResponse(BaseModel):
    """Schema for thread response."""

    id: int
    title: str
    format: str
    issues_remaining: int
    queue_position: int
    status: str
    last_rating: float | None
    last_activity_at: datetime | None
    review_url: str | None
    last_review_at: datetime | None
    notes: str | None
    is_test: bool
    created_at: datetime


class ReactivateRequest(BaseModel):
    """Schema for reactivating a completed thread."""

    thread_id: int
    issues_to_add: int = Field(..., gt=0)
