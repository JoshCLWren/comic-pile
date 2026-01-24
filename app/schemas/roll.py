"""Roll-related Pydantic schemas for request/response validation."""

from pydantic import BaseModel


class RollResponse(BaseModel):
    """Schema for roll response."""

    thread_id: int
    title: str
    die_size: int
    result: int


class OverrideRequest(BaseModel):
    """Schema for manual thread override."""

    thread_id: int
