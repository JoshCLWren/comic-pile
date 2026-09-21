"""Roll v2 bootstrap and rate response schemas.

Contract-only frozen DTOs for issue #2716. No synchronous provider calls and
no projection work live here; the v2 bootstrap derives canonical identity
from stored mappings only (unavailable identity yields null canonical id and
null canonical-series stats per #1401, never a thread-title substitution).
"""

from datetime import datetime
from enum import Enum
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.roll import RollRecoveryInfo
from app.schemas.session import ActiveThreadInfo, SessionBandwidthState, SessionMode
from app.schemas.thread import ThreadResponse


class IdentityState(str, Enum):
    """Derived identity states for rollable items."""

    CONFIRMED = "confirmed"
    CANDIDATE = "candidate"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"


class RouteKind(str, Enum):
    """Route kind for rollable items."""

    GROUP = "group"


class ProgressScope(str, Enum):
    """Progress scope for reader context."""

    CANONICAL_SERIES_RUN = "canonical_series_run"
    THREAD = "thread"


class RollableThread(BaseModel):
    """Thread information for rollable items."""

    id: int
    title: str
    format: str
    last_activity_at: str | None = None


class RollableIssue(BaseModel):
    """Issue information for rollable items."""

    id: int
    number: str
    canonical_series_title: str | None = None
    cover_url: str | None = None

    @field_validator("cover_url")
    @classmethod
    def cover_must_be_same_origin(cls, value: str | None) -> str | None:
        """Enforce the frozen cover contract: same-origin optimized URLs only.

        Args:
            value: Candidate cover URL.

        Returns:
            The value unchanged when null or same-origin.

        Raises:
            ValueError: If a non-null cover is not a same-origin
                ``/api/v1/images/optimize?...`` URL.
        """
        if value is None:
            return None
        if value.startswith("/api/v1/images/optimize"):
            return value
        raise ValueError("Roll v2 covers must be same-origin /api/v1/images/optimize URLs")


class RollableIdentity(BaseModel):
    """Identity information for rollable items."""

    source: Literal["comicvine", "unavailable"]
    canonical_series_id: str | None = None
    state: IdentityState
    series_mapping_state: IdentityState


class RollableReader(BaseModel):
    """Reader context for rollable items."""

    latest_rating: float | None = None
    average_rating: float | None = None
    rating_count: int | None = None
    read_count: int | None = None
    issue_count: int | None = None
    progress_scope: ProgressScope


class RollableRoute(BaseModel):
    """Route information for rollable items."""

    kind: RouteKind = Field(default=RouteKind.GROUP)
    name: str


class RollableItem(BaseModel):
    """A single rollable candidate thread with issue and context."""

    thread: RollableThread
    issue: RollableIssue  # Required/non-null as per spec
    identity: RollableIdentity
    reader: RollableReader
    routes: list[RollableRoute] = Field(default_factory=list, max_length=3)
    overflow_routes_count: int = Field(default=0, ge=0)


class RollLastRead(BaseModel):
    """Session-scoped last read information."""

    issue_id: int | None = None
    issue_number: str | None = None
    thread_id: int | None = None
    thread_title: str | None = None
    read_at: datetime | None = None


class RollV2BootstrapResponse(BaseModel):
    """V2 bootstrap response superset with rollable and last_read fields.

    Replaces the v1 roll_pool with rollable[] and adds nullable last_read.
    Maintains all v1 session/recovery/partition fields with unchanged semantics.
    """

    session_id: int
    user_id: int
    summary_limit: ClassVar[int] = 20

    current_die: int
    manual_die: int | None
    pending_thread_id: int | None
    last_rolled_result: int | None
    session_mode: SessionMode
    active_thread: ActiveThreadInfo | None
    roll_recovery: RollRecoveryInfo | None = None
    bandwidth: SessionBandwidthState
    rollable: list[RollableItem]  # Replaces roll_pool
    last_read: RollLastRead | None  # New nullable session-scoped field
    snoozed_threads: list[RollableThread] = Field(default_factory=list)
    snoozed_count: int
    skipped_thread_ids: list[int] = []
    skipped_threads: list[RollableThread] = []
    blocked_count: int
    blocked_threads: list[RollableThread] = []
    stale_thread_count: int
    stale_thread: RollableThread | None
    timezone: str | None = None

    @model_validator(mode="before")
    @classmethod
    def bound_summary_lists(cls, data: object) -> object:
        """Keep summary collections bounded even when stored session IDs grow."""
        if not isinstance(data, dict):
            return data

        for field_name in ("snoozed_threads", "skipped_threads", "blocked_threads"):
            values = data.get(field_name)
            if isinstance(values, list):
                data[field_name] = values[: cls.summary_limit]
        return data


class RollReconciliation(BaseModel):
    """Roll reconciliation information for rate response."""

    last_read: RollLastRead


class RateResponse(ThreadResponse):
    """Rate response extending ThreadResponse with roll reconciliation.

    Subclasses ThreadResponse so every current top-level field is preserved
    exactly, and adds ``roll_reconciliation.last_read`` for the v2 contract.
    Declared as the FastAPI ``response_model`` so the extra field is not
    filtered out.
    """

    roll_reconciliation: RollReconciliation | None = None
