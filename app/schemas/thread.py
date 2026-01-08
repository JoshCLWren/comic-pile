"""Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ThreadCreate(BaseModel):
    """Schema for creating a new thread."""

    title: str = Field(..., min_length=1)
    format: str = Field(..., min_length=1)
    issues_remaining: int = Field(..., ge=0)
    notes: str | None = None


class ThreadUpdate(BaseModel):
    """Schema for updating a thread."""

    title: str | None = Field(None, min_length=1)
    format: str | None = Field(None, min_length=1)
    issues_remaining: int | None = Field(None, ge=0)
    notes: str | None = None


class ThreadResponse(BaseModel):
    """Schema for thread response."""

    id: int
    title: str
    format: str
    issues_remaining: int
    position: int
    status: str
    last_rating: float | None
    last_activity_at: datetime | None
    review_url: str | None
    last_review_at: datetime | None
    notes: str | None
    created_at: datetime


class RollResponse(BaseModel):
    """Schema for roll response."""

    thread_id: int
    title: str
    die_size: int
    result: int


class OverrideRequest(BaseModel):
    """Schema for manual thread override."""

    thread_id: int


class ReactivateRequest(BaseModel):
    """Schema for reactivating a completed thread."""

    thread_id: int
    issues_to_add: int = Field(..., gt=0)


class RateRequest(BaseModel):
    """Schema for rating request."""

    rating: float = Field(..., ge=0.5, le=5.0)
    issues_read: int = Field(..., ge=1)
    finish_session: bool = Field(default=False)


class SessionResponse(BaseModel):
    """Schema for session response."""

    id: int
    started_at: datetime
    ended_at: datetime | None
    start_die: int
    manual_die: int | None
    user_id: int
    ladder_path: str
    active_thread: dict[str, Any] | None
    current_die: int
    last_rolled_result: int | None
