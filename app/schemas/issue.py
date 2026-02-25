"""Issue-related Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, Field


class IssueResponse(BaseModel):
    """Schema for issue response."""

    id: int
    thread_id: int
    issue_number: str
    status: str
    read_at: datetime | None
    created_at: datetime


class IssueCreate(BaseModel):
    """Schema for creating a new issue."""

    issue_number: str = Field(..., min_length=1, max_length=50)
    status: str = Field(default="unread", pattern="^(unread|read)$")
    read_at: datetime | None = None


class IssueUpdate(BaseModel):
    """Schema for updating an issue."""

    status: str | None = Field(None, pattern="^(unread|read)$")
    read_at: datetime | None = None


class IssueListResponse(BaseModel):
    """Schema for paginated issue list response."""

    issues: list[IssueResponse]
    total_count: int
    page_size: int
    next_page_token: str | None = None
