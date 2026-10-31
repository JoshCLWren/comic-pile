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
    rating: float | None = None


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


class IssueCreateRange(BaseModel):
    """Schema for creating issues from range format."""

    issue_range: str = Field(
        ..., min_length=1, description="Issue range like '1-25' or '1, 3, 5-7'"
    )
    insert_after_issue_id: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Insert new issues after this issue ID. Omit the field to place ordinary "
            "numeric issues in natural series order. Send explicit null to append at "
            "the end."
        ),
    )


class IssueMoveRequest(BaseModel):
    """Schema for moving an issue to a new position."""

    after_issue_id: int | None = Field(
        ...,
        ge=1,
        description="Move after this issue. null = move to position 1 (top).",
    )


class IssueReorderRequest(BaseModel):
    """Schema for bulk reordering issues within a thread."""

    issue_ids: list[int] = Field(
        ...,
        min_length=1,
        description="Ordered list of issue IDs representing the desired order.",
    )


class IssueBulkMarkReadRequest(BaseModel):
    """Schema for bulk marking issues as read."""

    issue_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Broadcast list of issue IDs to mark read.",
    )


class IssueBulkMarkUnreadRequest(BaseModel):
    """Schema for bulk marking issues as unread."""

    issue_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Broadcast list of issue IDs to mark unread.",
    )


class IssueOrderValidationResponse(BaseModel):
    """Schema for reporting in-thread dependency ordering conflicts."""

    warnings: list[str]
