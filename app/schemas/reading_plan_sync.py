"""Pydantic schemas for Reading Plan release-source sync."""

from __future__ import annotations

from datetime import datetime

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
