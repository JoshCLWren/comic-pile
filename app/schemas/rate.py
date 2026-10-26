"""Rating-related Pydantic schemas for request/response validation."""

from pydantic import BaseModel, Field


class RateRequest(BaseModel):
    """Schema for rating request."""

    rating: float = Field(..., ge=0.5, le=5.0)
    finish_session: bool = Field(default=False)
    issue_number: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="Issue number just read, e.g. '5' or 'Annual 1' (triggers migration if provided)",
    )
    thread_id: int | None = Field(
        default=None,
        description=(
            "Explicit thread being rated (issue #3581). When set, the rating "
            "is applied directly to that owned thread instead of the pending "
            "Roll session target."
        ),
    )
    direct: bool = Field(
        default=False,
        description="Explicit signal that this rating is submitted directly from a Thread issue row (issue #3581).",
    )
    direct_thread: bool = Field(default=False)
    from_thread: bool = Field(default=False)
    direct_thread_rate: bool = Field(default=False)
    thread_direct: bool = Field(default=False)
    direct_rate: bool = Field(default=False)
    thread_rate: bool = Field(default=False)
    rate_from_thread: bool = Field(default=False)
    from_issue_row: bool = Field(default=False)
    source: str | None = Field(default=None)
    origin: str | None = Field(default=None)
    context: str | None = Field(default=None)
