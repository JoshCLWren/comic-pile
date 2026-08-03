"""Roll-related Pydantic schemas for request/response validation."""

from typing import Any, ClassVar

from pydantic import BaseModel, Field, model_validator

from app.schemas.session import ActiveThreadInfo


class RollRequest(BaseModel):
    """Schema for roll request."""

    collection_id: int | None = Field(
        default=None,
        description="Optional collection ID to filter the roll pool by",
    )


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


class RollBootstrapThread(BaseModel):
    """Lightweight thread summary for the roll bootstrap pool."""

    id: int
    title: str
    format: str
    last_activity_at: str | None = None


class RollBootstrapResponse(BaseModel):
    """Bounded bootstrap payload for the Roll initial render.

    Returns only the retained data required for the first interactive screen.
    Does not include the full queue, collection data, or secondary detail panels.
    """

    summary_limit: ClassVar[int] = 20

    current_die: int
    manual_die: int | None
    pending_thread_id: int | None
    last_rolled_result: int | None
    active_thread: ActiveThreadInfo | None
    roll_pool: list[RollBootstrapThread]
    snoozed_threads: list[RollBootstrapThread]
    snoozed_count: int
    blocked_count: int
    blocked_threads: list[RollBootstrapThread]
    stale_thread_count: int
    stale_thread: RollBootstrapThread | None

    @model_validator(mode="before")
    @classmethod
    def bound_summary_lists(cls, data: Any) -> Any:
        """Keep summary collections bounded even when stored session IDs grow."""
        if not isinstance(data, dict):
            return data

        bounded = dict(data)
        for field_name in ("snoozed_threads", "blocked_threads"):
            values = bounded.get(field_name)
            if isinstance(values, list):
                bounded[field_name] = values[: cls.summary_limit]
        return bounded
