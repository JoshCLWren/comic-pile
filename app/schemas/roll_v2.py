"""Roll v2 bootstrap and rate response schemas.

Contract-only frozen DTOs for issue #2716. No synchronous provider calls and
no projection work live here; the v2 bootstrap derives canonical identity
from stored mappings only (unavailable identity yields null canonical id and
null canonical-series stats per #1401, never a thread-title substitution).
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from app.schemas.tags import TagResponse
from app.schemas.thread import ThreadResponse


class IdentityState(StrEnum):
    """Derived identity states for rollable items."""

    CONFIRMED = "confirmed"
    CANDIDATE = "candidate"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"


class RouteKind(StrEnum):
    """Route kind for rollable items."""

    GROUP = "group"


class ProgressScope(StrEnum):
    """Progress scope for reader context."""

    CANONICAL_SERIES_RUN = "canonical_series_run"
    THREAD = "thread"


class RollableThread(BaseModel):
    """Thread information for rollable items and Roll summaries."""

    id: int
    title: str
    format: str
    last_activity_at: str | None = None
    tags: list[TagResponse] = Field(default_factory=list)


class RollableIssue(BaseModel):
    """Issue information for rollable items."""

    id: int
    number: str
    canonical_series_title: str | None = None
    cover_url: str | None = None

    @field_validator("cover_url")
    @classmethod
    def cover_must_be_remote_image(cls, value: str | None) -> str | None:
        """Accept only direct, absolute provider image URLs, never a local proxy."""
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("https", "http") or not parts.hostname:
            raise ValueError("Roll v2 covers must be direct HTTP(S) image URLs")
        if parts.username or parts.password:
            raise ValueError("Roll v2 covers must not embed credentials")
        return value

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
