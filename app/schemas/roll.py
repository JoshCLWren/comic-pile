"""Roll-related Pydantic schemas for request/response validation."""

from pydantic import BaseModel


class RollResponse(BaseModel):
    """Schema for roll response."""

    thread_id: int
    title: str
    format: str
    issues_remaining: int
    queue_position: int
    die_size: int
    result: int
    offset: int
    snoozed_count: int
    issue_id: int | None = None
    issue_number: str | None = None
    next_issue_id: int | None = None
    next_issue_number: str | None = None
    total_issues: int | None = None
    reading_progress: str | None = None


class OverrideRequest(BaseModel):
    """Schema for manual thread override."""

    thread_id: int
