"""API endpoints for Reading Plan release-source sync."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.reading_plan_sync import (
    SyncReport,
    SyncRequest,
    SyncResponse,
    SyncStatusResponse,
    SyncStatusSource,
)
from app.services.reading_plan_sync_service import SyncReport as ServiceReport
from app.services.reading_plan_sync_service import (
    list_sync_status,
    sync_released_issues,
)

router = APIRouter(tags=["reading-plan-sync"])


def _to_report(report: ServiceReport) -> SyncReport:
    """Project the service report onto its API schema.

    Args:
        report: Service-layer run report.

    Returns:
        The API-shaped report.
    """
    return SyncReport(
        total_sources=report.total_sources,
        enabled_sources=report.enabled_sources,
        checked_sources=report.checked_sources,
        successful_sources=report.successful_sources,
        failed_sources=report.failed_sources,
        issues_checked=report.issues_checked,
        created_issues=report.created_issues,
        reused_issues=report.reused_issues,
        future_skips=report.future_skips,
        unknown_date_skips=report.unknown_date_skips,
        conflicts=report.conflicts,
        issue_failures=report.issue_failures,
        failures=[
            {
                "source_id": failure.source_id,
                "plan_id": failure.plan_id,
                "thread_id": failure.thread_id,
                "volume_id": failure.volume_id,
                "error": failure.error,
            }
            for failure in report.failures
        ],
    )


def _message(report: ServiceReport) -> str:
    """Build the human-readable run summary.

    Args:
        report: Service-layer run report.

    Returns:
        One-line summary of the run.
    """
    return (
        f"Sync completed: {report.successful_sources} successful, "
        f"{report.failed_sources} failed, "
        f"{report.created_issues} created, "
        f"{report.reused_issues} reused"
    )


@router.post("/reading-plan-sync/sync", response_model=SyncResponse)
async def sync_released_issues_endpoint(
    payload: SyncRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncResponse:
    """Sync the caller's followed ComicVine volumes and adopt released issues.

    Only the authenticated user's release sources are evaluated. An issue is
    adopted only when ComicVine reports a ``store_date`` on or before ``as_of``.
    """
    report = await sync_released_issues(
        db,
        user_id=current_user.id,
        as_of=payload.as_of,
        refresh=payload.refresh,
    )
    # Project before committing: the report holds only plain values, so no ORM
    # attribute is read after the commit expires the session state.
    response = SyncResponse(
        success=report.success,
        message=_message(report),
        result=_to_report(report),
    )
    await db.commit()
    return response


@router.get("/reading-plan-sync/status", response_model=SyncStatusResponse)
async def get_sync_status(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncStatusResponse:
    """Report persisted sync state for the caller's release sources."""
    statuses = await list_sync_status(db, user_id=current_user.id)
    return SyncStatusResponse(
        total_sources=len(statuses),
        enabled_sources=sum(1 for status in statuses if status.enabled),
        sources=[
            SyncStatusSource(
                id=status.source_id,
                reading_plan_id=status.plan_id,
                thread_id=status.thread_id,
                external_identity_id=status.external_identity_id,
                provider_volume_id=status.provider_volume_id,
                enabled=status.enabled,
                last_synced_at=status.last_synced_at,
            )
            for status in statuses
        ],
    )