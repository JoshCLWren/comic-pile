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


class OverrideRequest(BaseModel):
    """Schema for manual thread override."""

    thread_id: int
