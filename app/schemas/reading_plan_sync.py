"""Pydantic schemas for Reading Plan release-source sync."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SyncRequest(BaseModel):
    """Request one release-source sync run for the authenticated user."""

    as_of: datetime = Field(
        description=(
            "UTC timestamp defining the release boundary. Only issues whose ComicVine "
            "store_date is on or before this instant are adopted."
        )
    )
    refresh: bool = Field(
        default=True,
        description="Force live provider requests instead of reading the ComicVine cache.",
    )


class SourceSyncFailure(BaseModel):
    """One source that could not be evaluated during a sync run."""

    source_id: int
    plan_id: int
    thread_id: int
    volume_id: int
    error: str


class SyncReport(BaseModel):
    """Structured per-run counters for observability."""

    total_sources: int
    enabled_sources: int
    checked_sources: int
    successful_sources: int
    failed_sources: int
    issues_checked: int
    created_issues: int
    reused_issues: int
    future_skips: int
    unknown_date_skips: int
    conflicts: int
    issue_failures: int
    excluded_sources: int = 0
    excluded_issues: int = 0
    skipped_sources: int = 0
    failures: list[SourceSyncFailure]


class SyncResponse(BaseModel):
    """Response of a completed release-source sync run."""

    success: bool
    message: str
    result: SyncReport


class SyncStatusSource(BaseModel):
    """One release source's persisted sync state."""

    id: int
    reading_plan_id: int
    thread_id: int
    external_identity_id: int
    provider_volume_id: str
    enabled: bool
    last_synced_at: datetime | None


class SyncStatusResponse(BaseModel):
    """Sync state for every release source owned by the authenticated user."""

    total_sources: int
    enabled_sources: int
    sources: list[SyncStatusSource]


class ScheduledUserFailure(BaseModel):
    """One owner whose sync failed during a scheduled run."""

    user_id: int
    error: str


class ScheduledSyncReport(BaseModel):
    """Aggregate, secret-free metrics for one scheduled release-sync run."""

    status: Literal["completed", "already_running"]
    as_of: datetime
    users_total: int
    users_processed: int
    users_failed: int
    users_deferred: int
    truncated: bool
    duration_ms: int
    total_sources: int
    enabled_sources: int
    checked_sources: int
    successful_sources: int
    failed_sources: int
    issues_checked: int
    created_issues: int
    reused_issues: int
    future_skips: int
    unknown_date_skips: int
    conflicts: int
    issue_failures: int
    excluded_sources: int
    skipped_sources: int
    excluded_issues: int
    failures: list[SourceSyncFailure]
    user_failures: list[ScheduledUserFailure]


class ScheduledSyncResponse(BaseModel):
    """Response of one machine-triggered scheduled release-sync run."""

    success: bool
    status: Literal["completed", "already_running"]
    message: str
    result: ScheduledSyncReport
