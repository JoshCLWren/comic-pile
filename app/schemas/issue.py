"""Issue-related Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, Field


class IssueResponse(BaseModel):
    """Schema for issue response."""

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


class IssueCreateRange(BaseModel):
    """Schema for creating issues from range format."""

    issue_range: str = Field(
        ..., min_length=1, description="Issue range like '1-25' or '1, 3, 5-7'"
    )
    insert_after_issue_id: int | None = Field(
        default=None,
        ge=1,
        description="Insert new issues after this issue ID. If null, append to end.",
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


class IssueOrderValidationResponse(BaseModel):
    """Schema for reporting in-thread dependency ordering conflicts."""

    warnings: list[str]


class PreviousIssueInfo(BaseModel):
    """Schema for the previous issue in canonical series context."""

    issue_id: int
    issue_number: str
    thread_id: int
    thread_title: str
    effective_rating: float | None = None
    is_read: bool = False


class RecentRatingEntry(BaseModel):
    """Schema for a single recent rating entry in canonical series context."""

    rating: float
    rated_at: str
    thread_id: int
    thread_title: str


class CanonicalSeriesInfo(BaseModel):
    """Schema for canonical series analytics context."""

    identity_source: str = "unavailable"
    average_rating: float | None = None
    rated_count: int = 0
    previous_issue: PreviousIssueInfo | None = None
    recent_ratings: list[RecentRatingEntry] = []
    highest_rating: float | None = None
    lowest_rating: float | None = None


class CrossoverNodeInfo(BaseModel):
    """Schema for one participation node in a crossover group."""

    node_type: str
    node_id: int
    thread_id: int | None = None
    issue_id: int | None = None
    issue_number: str | None = None
    thread_title: str | None = None
    is_read: bool = False


class CrossoverAnalyticsInfo(BaseModel):
    """Schema for crossover analytics in reader context."""

    group_id: int
    group_name: str
    average_rating: float | None = None
    rated_count: int = 0
    read_count: int = 0
    node_count: int = 0
    nodes: list[CrossoverNodeInfo] = []


class ReaderContextResponse(BaseModel):
    """Schema for reader-context analytics on a single issue."""

    canonical_series: CanonicalSeriesInfo | None = None
    crossover_panel: list[CrossoverAnalyticsInfo] = []
