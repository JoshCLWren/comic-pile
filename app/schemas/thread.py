"""Pydantic schemas for request/response validation."""

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
    position: int
    status: str
    last_rating: float | None
    last_activity_at: datetime | None
    review_url: str | None
    last_review_at: datetime | None
    notes: str | None
    is_test: bool
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


class ActiveThreadInfo(BaseModel):
    """Schema for active thread information in session response."""

    id: int | None
    title: str
    format: str
    issues_remaining: int
    position: int
    last_rolled_result: int | None


class SessionResponse(BaseModel):
    """Schema for session response."""

    id: int
    started_at: datetime
    ended_at: datetime | None
    start_die: int
    manual_die: int | None
    user_id: int
    ladder_path: str
    active_thread: ActiveThreadInfo | None
    current_die: int
    last_rolled_result: int | None
    has_restore_point: bool
    snapshot_count: int


class EventDetail(BaseModel):
    """Schema for event detail in session details."""

    id: int
    type: str
    timestamp: datetime
    thread_title: str | None
    die: int | None = None
    result: int | None = None
    selection_method: str | None = None
    rating: float | None = None
    issues_read: int | None = None
    queue_move: str | None = None
    die_after: int | None = None


class SessionDetailsResponse(BaseModel):
    """Schema for session details with all events."""

    session_id: int
    started_at: datetime
    ended_at: datetime | None
    start_die: int
    ladder_path: str
    narrative_summary: dict[str, list[str]]
    current_die: int
    events: list[EventDetail]


class SnapshotResponse(BaseModel):
    """Schema for snapshot response."""

    id: int
    session_id: int
    created_at: datetime
    description: str | None


class SnapshotsListResponse(BaseModel):
    """Schema for snapshots list response."""

    session_id: int
    snapshots: list[SnapshotResponse]
