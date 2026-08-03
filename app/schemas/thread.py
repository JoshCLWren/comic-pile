"""Thread-related Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, Field


class ThreadCreate(BaseModel):
    """Schema for creating a new thread."""

    title: str = Field(..., min_length=1, max_length=200)
    format: str = Field(..., min_length=1)
    issues_remaining: int = Field(..., ge=0)
    total_issues: int | None = Field(None, ge=1)
    notes: str | None = None
    is_test: bool = False


class ThreadUpdate(BaseModel):
    """Schema for updating a thread."""

    title: str | None = Field(None, min_length=1, max_length=200)
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
    notes: str | None
    is_test: bool
    is_blocked: bool = False
    blocking_reasons: list[str] = []
    created_at: datetime
    total_issues: int | None = None
    reading_progress: str | None = None
    next_unread_issue_id: int | None = None
    next_unread_issue_number: str | None = None


class ThreadDetail(ThreadResponse):
    """Schema for thread detail view (single thread with full detail fields)."""


class QueueThreadListItem(BaseModel):
    """Schema for a single thread in the list/queue view.

    A deliberate subset of ThreadResponse. The list view does not need
    detail-only fields like last_rating, is_test, or reading_progress,
    which reduces payload size for large lists.
    """

    id: int
    title: str
    format: str
    issues_remaining: int
    queue_position: int
    status: str
    last_activity_at: datetime | None
    is_blocked: bool = False
    blocking_reasons: list[str] = []
    total_issues: int | None = None
    next_unread_issue_number: str | None = None
    notes: str | None = None
    created_at: datetime


class ReactivateRequest(BaseModel):
    """Schema for reactivating a completed thread."""

    thread_id: int
    issues_to_add: int = Field(..., gt=0)


class ThreadListResponse(BaseModel):
    """Schema for paginated thread list response."""

    threads: list[ThreadResponse]
    next_page_token: str | None = None


class QueueThreadListResponse(BaseModel):
    """Schema for paginated thread list response using the queue-optimized item."""

    threads: list[QueueThreadListItem]
    next_page_token: str | None = None
