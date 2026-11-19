"""Machine-triggered operational endpoints for Vercel Cron invocations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.access_control import require_cron_secret
from app.database import get_db
from app.schemas.comicvine import MetadataRepairDrainResponse
from app.schemas.reading_plan_sync import (
    ScheduledSyncReport,
    ScheduledSyncResponse,
    ScheduledUserFailure,
    SourceSyncFailure,
)
from app.services.reading_plan_sync_service import (
    ScheduledSyncReport as ServiceScheduledReport,
)
from app.services.reading_plan_sync_service import run_scheduled_release_sync
from app.services.comicvine_metadata_repair import drain_due_metadata_repairs

router = APIRouter(
    tags=["cron"],
    dependencies=[Depends(require_cron_secret)],
    include_in_schema=False,
)


def _to_report(report: ServiceScheduledReport) -> ScheduledSyncReport:
    """Project the service report onto its API schema.

    Args:
        report: Service-layer scheduled-run report.

    Returns:
        The API-shaped report.
    """
    return ScheduledSyncReport(
        status=report.status,
        as_of=report.as_of,
        users_total=report.users_total,
        users_processed=report.users_processed,
        users_failed=report.users_failed,
        users_deferred=report.users_deferred,
        truncated=report.truncated,
        duration_ms=report.duration_ms,
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
        excluded_sources=report.excluded_sources,
        skipped_sources=report.skipped_sources,
        excluded_issues=report.excluded_issues,
        failures=[
            SourceSyncFailure(
                source_id=failure.source_id,
                plan_id=failure.plan_id,
                thread_id=failure.thread_id,
                volume_id=failure.volume_id,
                error=failure.error,
            )
            for failure in report.failures
        ],
        user_failures=[
            ScheduledUserFailure(user_id=failure.user_id, error=failure.error)
            for failure in report.user_failures
        ],
    )


def _message(report: ServiceScheduledReport) -> str:
    """Build the human-readable scheduled-run summary.

    Args:
        report: Service-layer scheduled-run report.

    Returns:
        One-line summary of the run.
    """
    if report.status == "already_running":
        return "Release sync skipped: another scheduled run is already active"
    return (
        f"Scheduled release sync completed: {report.users_processed} users processed, "
        f"{report.created_issues} created, {report.reused_issues} reused, "
        f"{report.failed_sources} sources failed, "
        f"{report.users_deferred} users deferred"
    )


@router.get(
    "/cron/release-sync",
    response_model=ScheduledSyncResponse,
    include_in_schema=False,
)
async def release_sync_cron(
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> ScheduledSyncResponse:
    """Run the daily release-source sync for every owner with enabled sources.

    Authorization is enforced by the router-level ``require_cron_secret``
    dependency, which rejects anonymous and incorrectly authenticated requests
    before this handler runs. All synchronization behavior lives in the service
    layer; this handler only projects the structured result and owns the
    request transaction's commit.
    """
    # A cron response must never be cached or replayed by an intermediary.
    response.headers["Cache-Control"] = "no-store"

    report = await run_scheduled_release_sync(db)
    # Project before committing: the report holds only plain values, so no ORM
    # attribute is read after the commit expires the session state.
    payload = ScheduledSyncResponse(
        success=report.success,
        status=report.status,
        message=_message(report),
        result=_to_report(report),
    )
    await db.commit()
    return payload


@router.get(
    "/cron/comicvine-metadata-repair",
    include_in_schema=False,
)
async def comicvine_metadata_repair_cron(
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> MetadataRepairDrainResponse:
    """Run one bounded drain of durable metadata repair requests.

    Authorization is enforced by the router-level ``require_cron_secret``
    dependency.

    Args:
        db: Async database session delegated to the service.
        response: HTTP response carrying no-store headers.

    Returns:
        Counts for this bounded repair drain.
    """
    response.headers["Cache-Control"] = "no-store"
    # A daily fallback can safely drain up to ten due jobs per invocation.
    report = await drain_due_metadata_repairs(db=db, limit=10)
    return MetadataRepairDrainResponse(
        claimed=report.claimed,
        completed=report.completed,
        no_credits=report.no_credits,
        deferred=report.deferred,
        failed=report.failed,
        provider_configured=report.provider_configured,
    )
