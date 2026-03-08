"""Session-related Pydantic schemas for request/response validation."""

from datetime import UTC, datetime

from pydantic import BaseModel, field_serializer


def _to_utc_iso(value: datetime) -> str:
    """Convert datetime to ISO 8601 format with timezone.

    Ensures naive datetimes are treated as UTC for consistent serialization.

    Args:
        value: The datetime value to serialize.

    Returns:
        ISO 8601 formatted string with timezone.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


class SnoozedThreadInfo(BaseModel):
    """Schema for snoozed thread information in session response."""

    id: int
    title: str


class ActiveThreadInfo(BaseModel):
    """Schema for active thread information in session response."""

    id: int | None
    title: str
    format: str
    issues_remaining: int
    queue_position: int
    last_rolled_result: int | None
    total_issues: int | None = None
    reading_progress: str | None = None
    issue_id: int | None = None
    issue_number: str | None = None
    next_issue_id: int | None = None
    next_issue_number: str | None = None


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
    snoozed_thread_ids: list[int] = []
    snoozed_threads: list[SnoozedThreadInfo] = []
    pending_thread_id: int | None = None

    @field_serializer("started_at", "ended_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        """Serialize datetime to ISO 8601 format with timezone.

        Ensures naive datetimes are treated as UTC for consistent serialization.

        Args:
            value: The datetime value to serialize.

        Returns:
            ISO 8601 formatted string with timezone, or None if value is None.
        """
        if value is None:
            return None
        return _to_utc_iso(value)


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

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        """Serialize event timestamp to ISO 8601 format with timezone.

        Ensures naive datetimes are treated as UTC for consistent serialization.

        Args:
            value: The datetime value to serialize.

        Returns:
            ISO 8601 formatted string with timezone.
        """
        return _to_utc_iso(value)


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

    @field_serializer("started_at", "ended_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        """Serialize datetime to ISO 8601 format with timezone.

        Ensures naive datetimes are treated as UTC for consistent serialization.

        Args:
            value: The datetime value to serialize.

        Returns:
            ISO 8601 formatted string with timezone, or None if value is None.
        """
        if value is None:
            return None
        return _to_utc_iso(value)
