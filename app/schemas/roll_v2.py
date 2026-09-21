"""Roll v2 bootstrap and rate response schemas."""

from datetime import datetime
from enum import Enum
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.continuity_blocking import ContinuityBlocker
from app.schemas.roll import RollRecoveryInfo, RollRecoveryPrerequisite, RollRecoveryChainNode, RollRecoveryDiagnostic
from app.schemas.session import ActiveThreadInfo, BandwidthSource, IntentSource, SessionBandwidthState, SessionMode
from comic_pile.recommendation_selection import Bandwidth, Intent


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


class RollableIdentity(BaseModel):
    """Identity information for rollable items."""
    
    source: str
    canonical_series_id: str | None = None
    state: IdentityState
    series_mapping_state: str | None = None


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
    routes: list[RollableRoute] = Field(default_factory=list)
    overflow_routes_count: int = 0


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


class RateResponse(BaseModel):
    """Rate response extending ThreadResponse with roll reconciliation.
    
    Preserves all current ThreadResponse top-level fields and adds
    roll_reconciliation.last_read for v2 contract compatibility.
    """
    
    # All existing ThreadResponse fields
    id: int
    title: str
    format: str
    issues_remaining: int
    queue_position: int
    status: str
    last_rating: float | None = None
    last_activity_at: str | None = None
    notes: str | None = None
    is_test: bool = False
    is_blocked: bool = False
    blocking_reasons: list[str] = Field(default_factory=list)
    created_at: datetime
    total_issues: int | None = None
    reading_progress: str | None = None
    next_unread_issue_id: int | None = None
    next_unread_issue_number: str | None = None
    
    # New v2 field
    roll_reconciliation: RollReconciliation | None = None