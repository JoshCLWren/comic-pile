"""Thread-related Pydantic schemas for request/response validation."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Upper bound on manually entered creator credits stored on one thread.
MAX_MANUAL_CREATOR_CREDITS = 50
#: Upper bound on one stored creator display name.
MAX_CREATOR_NAME_LENGTH = 200
#: Upper bound on the number of roles stored for one creator credit.
MAX_MANUAL_ROLES_PER_CREDIT = 12
#: Upper bound on one stored role token.
MAX_MANUAL_ROLE_LENGTH = 60


def normalize_manual_creator_credits(
    raw: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Coerce raw client-supplied creator credits into the stored shape.

    The stored column is a JSON document, so this is the only boundary that
    decides what reaches persistence. Entries without a usable name are
    dropped, every entry is reduced to the ``name``/``roles`` shape, and both
    the entry count and the per-entry token lengths are bounded.

    Args:
        raw: Client-supplied credit candidates.

    Returns:
        Normalized, bounded credit dictionaries ready for persistence.
    """
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if len(normalized) >= MAX_MANUAL_CREATOR_CREDITS:
            break
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        clean_name = " ".join(name.split())[:MAX_CREATOR_NAME_LENGTH]
        if not clean_name:
            continue
        roles: list[str] = []
        raw_roles = item.get("roles")
        if isinstance(raw_roles, list):
            for role in raw_roles:
                if not isinstance(role, str):
                    continue
                clean_role = " ".join(role.split())[:MAX_MANUAL_ROLE_LENGTH]
                if clean_role and clean_role not in roles:
                    roles.append(clean_role)
                if len(roles) >= MAX_MANUAL_ROLES_PER_CREDIT:
                    break
        normalized.append({"name": clean_name, "roles": roles})
    return normalized


class ThreadCreate(BaseModel):
    """Schema for creating a new thread."""

    title: str = Field(..., min_length=1, max_length=200)
    format: str = Field(..., min_length=1)
    issues_remaining: int = Field(..., ge=0)
    total_issues: int | None = Field(None, ge=1)
    notes: str | None = None
    manual_creator_credits: list[dict[str, Any]] = Field(default_factory=list)
    is_test: bool = False

    @field_validator("manual_creator_credits")
    @classmethod
    def _bounded_manual_credits(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Bound and reshape manually entered creator credits.

        Args:
            value: Raw credits accepted by field validation.

        Returns:
            The normalized credit list that is persisted.
        """
        return normalize_manual_creator_credits(value)


class ThreadUpdate(BaseModel):
    """Schema for updating a thread."""

    title: str | None = Field(None, min_length=1, max_length=200)
    format: str | None = Field(None, min_length=1)
    issues_remaining: int | None = Field(None, ge=0)
    notes: str | None = None
    manual_creator_credits: list[dict[str, Any]] | None = None
    is_test: bool | None = None

    @field_validator("manual_creator_credits")
    @classmethod
    def _bounded_manual_credits(
        cls, value: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        """Bound and reshape manually entered creator credits.

        Args:
            value: Raw credits accepted by field validation, or ``None`` when
                the caller is not updating them.

        Returns:
            The normalized credit list, or ``None`` when the field is absent.
        """
        if value is None:
            return None
        return normalize_manual_creator_credits(value)


class ThreadResponse(BaseModel):
    """Schema for thread response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    format: str
    issues_remaining: int
    queue_position: int
    status: str
    last_rating: float | None
    last_activity_at: datetime | None
    notes: str | None
    is_test: bool
    is_blocked: bool = False
    blocking_reasons: list[str] = []
    created_at: datetime
    total_issues: int | None = None
    reading_progress: str | None = None
    next_unread_issue_id: int | None = None
    next_unread_issue_number: str | None = None
    manual_creator_credits: list[dict[str, object]] = []


class ThreadDetail(ThreadResponse):
    """Schema for thread detail view (single thread with full detail fields)."""


class ComicVineMappingStatus(StrEnum):
    """ComicVine mapping health status for a thread.

    - ``not_applicable``: Thread does not use issue tracking (legacy counter-based).
    - ``fully_mapped``: All in-scope issues have confirmed ComicVine mappings.
    - ``partial``: Some issues confirmed, some unresolved/unmapped.
    - ``unresolved``: Issues exist but none have confirmed mappings.
    - ``needs_review``: Conflicting/ambiguous mappings requiring human review.
    """

    not_applicable = "not_applicable"
    fully_mapped = "fully_mapped"
    partial = "partial"
    unresolved = "unresolved"
    needs_review = "needs_review"


class ComicVineMappingHealth(BaseModel):
    """Compact ComicVine mapping health projection for a queue thread.

    Derived from stored canonical issue mappings only. No live provider calls.
    Counts are scoped to the issues represented by the Queue thread.
    """

    status: ComicVineMappingStatus
    tracked_issue_count: int = Field(..., ge=0, description="Total issues in this thread's scope")
    confirmed_issue_count: int = Field(..., ge=0, description="Issues with confirmed ComicVine mappings")
    needs_mapping_count: int = Field(..., ge=0, description="Issues with no confirmed mapping (unresolved/candidate)")
    needs_review_count: int = Field(..., ge=0, description="Issues with conflicting/ambiguous mappings")

    model_config = ConfigDict(frozen=True)


class QueueThreadListItem(BaseModel):
    """Schema for a single thread in the list/queue view.

    A deliberate subset of ThreadResponse. The list view does not need
    detail-only fields like last_rating, is_test, or reading_progress,
    which reduces payload size for large lists.
    """

    id: int
    title: str
    format: str
    issues_remaining: int
    queue_position: int
    status: str
    last_activity_at: datetime | None
    is_blocked: bool = False
    blocking_reasons: list[str] = []
    total_issues: int | None = None
    next_unread_issue_number: str | None = None
    notes: str | None = None
    created_at: datetime
    comicvine_mapping: ComicVineMappingHealth | None = None
    manual_creator_credits: list[dict[str, object]] = []


class ReactivateRequest(BaseModel):
    """Schema for reactivating a completed thread."""

    thread_id: int
    issues_to_add: int = Field(..., gt=0)


class ThreadListResponse(BaseModel):
    """Schema for paginated thread list response."""

    threads: list[ThreadResponse]
    next_page_token: str | None = None


class QueueThreadListResponse(BaseModel):
    """Schema for paginated thread list response using the queue-optimized item.

    ``active_count`` is the authoritative total number of active threads in the
    user's queue. It is computed from the whole queue, never from the loaded
    page, and is independent of any search or sort filter (see issue #2568).
    """

    threads: list[QueueThreadListItem]
    next_page_token: str | None = None
    active_count: int = Field(0, ge=0)
