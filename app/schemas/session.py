"""Session API schemas and response models.

WARNING: ActiveThreadInfo.issue_id and ActiveThreadInfo.issue_number are deprecated.
Always use next_issue_id and next_issue_number instead. The old fields are kept for
backward compatibility but will be removed in a future version.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer


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
    issues_read: int | None = None
    last_rating: float | None = None

    issue_id: int | None = Field(
        default=None,
        description="DEPRECATED: Always equals next_issue_id. Use next_issue_id instead.",
    )
    issue_number: str | None = Field(
        default=None,
        description="DEPRECATED: Always equals next_issue_number. Use next_issue_number instead.",
    )
    next_issue_id: int | None = Field(default=None, description="The next unread issue ID to read")
    next_issue_number: str | None = Field(
        default=None, description="The next unread issue number (e.g., '5', 'Annual 1')"
    )


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
    description: str | None = None
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


class SessionListResponse(BaseModel):
    """Schema for paginated session list response."""

    sessions: list[SessionResponse]
    next_page_token: str | None = None


class SessionListItem(BaseModel):
    """Schema for a single session in the history list view.

    A deliberate subset of SessionResponse. The list view does not need
    snoozed_thread_ids, snoozed_threads, or pending_thread_id, which
    reduces payload size for session history lists.
    """

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


class SessionHistoryListResponse(BaseModel):
    """Schema for paginated session history list response."""

    sessions: list[SessionListItem]
    next_page_token: str | None = None


class SessionMode(BaseModel):
    """Canonical session mode state for Roll bootstrap and frontend rendering.

    Describes the active and predicted reading bandwidth and intent, together
    with the confidence, source, and version metadata needed for the reading-
    mode UI. When all fields are ``None`` the session is in the legacy null
    state and the frontend should treat it as the default balanced mode.
    """

    active_bandwidth: str | None = Field(
        default=None,
        description="Current active bandwidth: light, balanced, deep, or null for legacy",
    )
    predicted_bandwidth: str | None = Field(
        default=None, description="Algorithm-predicted bandwidth for this session"
    )
    bandwidth_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confidence in the bandwidth prediction"
    )
    bandwidth_source: Literal["manual", "inferred"] | None = Field(
        default=None,
        description="Origin of the bandwidth value: manual user override or algorithm inference",
    )
    bandwidth_version: str | None = Field(
        default=None, description="Version tag for the bandwidth inference algorithm"
    )
    active_intent: str | None = Field(
        default=None,
        description="Current active intent: balanced, momentum, familiar, explore, random, or null",
    )
    predicted_intent: str | None = Field(
        default=None, description="Algorithm-predicted intent for this session"
    )
    intent_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confidence in the intent prediction"
    )
    intent_source: Literal["manual", "inferred"] | None = Field(
        default=None,
        description="Origin of the intent value: manual user override or algorithm inference",
    )
    intent_version: str | None = Field(
        default=None, description="Version tag for the intent inference algorithm"
    )
    session_mode_correction_guidance: dict | None = Field(
        default=None,
        description="Compact guidance when mode differs from prediction (null when no correction)",
    )
