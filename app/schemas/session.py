"""Session-related Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel


class ActiveThreadInfo(BaseModel):
    """Schema for active thread information in session response."""

    id: int | None
    title: str
    format: str
    issues_remaining: int
    queue_position: int
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
