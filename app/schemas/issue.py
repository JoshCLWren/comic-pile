"""Issue-related Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.comicvine import ComicVineCreator


class IssueResponse(BaseModel):
    """Schema for issue response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    thread_id: int
    issue_number: str
    position: int
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


class IssueCreatorsEntry(BaseModel):
    """Stored ComicVine creator credits for one thread issue."""

    issue_id: int
    creators: list[ComicVineCreator] = Field(default_factory=list)


class ThreadIssueCreatorsResponse(BaseModel):
    """Bulk per-issue ComicVine creator credits for one thread.

    Issues without a confirmed ComicVine mapping (or without stored credit
    arrays) are omitted; callers fall back to the series' manual creator
    credits for those rows.
    """

    thread_id: int
    issues: list[IssueCreatorsEntry] = Field(default_factory=list)


