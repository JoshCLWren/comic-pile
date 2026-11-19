"""Deterministic sync of followed ComicVine volumes into Reading Plan threads.

The service evaluates each enabled release source the reader owns, fetches the
authoritative provider roster through the existing
:meth:`ComicVineClient.fetch_volume_issues` pagination contract, and adopts only
issues that have actually reached release.

Guarantees:

- Sources are scoped to the requesting user; one reader's sync never touches
  another reader's plans, threads, or issues.
- Adoption reuses the shared
  :func:`~app.services.provider_issue_adoption.adopt_comicvine_issue` primitive,
  so retries and duplicate subscriptions converge on one canonical Issue instead
  of creating a second copy.
- The release gate uses ComicVine's ``store_date`` only, normalized to UTC. A
  missing, unparseable, or future ``store_date`` is skipped and reported; it is
  never inferred from ``cover_date`` or from the issue number.
- ``last_synced_at`` advances only for sources whose roster was actually
  retrieved and evaluated, so a failed source never appears current.
- One bad volume or issue is isolated; the remaining sources still sync.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.repositories import reading_plan_release_source_repository as repo
from app.repositories import issue_repository, thread_repository
from app.repositories.reading_list_authoring_repository import lock_reader
from app.services.release_exclusion_service import comicvine_volume_id, load_release_exclusions
from app.services.provider_issue_adoption import adopt_comicvine_issue
from comic_pile.comicvine_provider import ComicVineClient

logger = logging.getLogger(__name__)

COMICVINE_PROVIDER = "comicvine"

_UNKNOWN_VOLUME_ID = -1

#: Transaction-scoped advisory-lock key for scheduled (Vercel Cron) runs.
#: A fixed global key keeps overlapping cron invocations from double-adopting
#: issues even when Vercel delivers two requests to independent instances.
RELEASE_SYNC_CRON_LOCK_KEY = 1_065_200_001

#: Default wall-clock budget for one scheduled run. The serverless function must
#: answer within its platform limit, so the runner stops starting new owners at
#: this boundary and reports the remainder as deferred for the next daily run.
DEFAULT_CRON_MAX_DURATION_SECONDS = 50.0


def build_comicvine_client() -> ComicVineClient:
    """Build a ComicVine client from the environment configuration.

    Returns:
        A configured provider client.

    Raises:
        ValueError: When no ComicVine API key is configured.
    """
    api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
    cache_dir = Path(os.environ.get("COMICVINE_CACHE_DIR", "/tmp/comicpile-comicvine"))
    return ComicVineClient(api_key, cache_dir)


def parse_store_date(value: object) -> datetime | None:
    """Normalize a ComicVine ``store_date`` to an aware UTC instant.

    ComicVine returns dates in several shapes: ``YYYY-MM-DD``, an ISO timestamp
    with a ``Z`` suffix, or a timestamp with a numeric offset. A bare date means
    midnight UTC. Anything unparseable returns None so the caller reports an
    unknown-date skip rather than guessing.

    Args:
        value: Raw provider value for ``store_date``.

    Returns:
        A timezone-aware UTC instant, or None when absent or unparseable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith(("Z", "z")):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            logger.info("reading_plan_sync_unparseable_store_date value=%s", value)
            return None
    else:
        logger.info("reading_plan_sync_unparseable_store_date value=%r", value)
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _as_aware_utc(value: datetime) -> datetime:
    """Coerce a caller-supplied boundary instant to aware UTC.

    Args:
        value: Boundary instant supplied by the caller.

    Returns:
        The same instant expressed in UTC, assuming UTC when naive.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SyncSourceStatus:
    """Persisted sync state for one release source."""

    source_id: int
    plan_id: int
    thread_id: int
    external_identity_id: int
    provider_volume_id: str
    enabled: bool
    last_synced_at: datetime | None


async def list_sync_status(
    db: AsyncSession, *, user_id: int
) -> list[SyncSourceStatus]:
    """Return persisted sync state for every release source the user owns.

    Args:
        db: Database session.
        user_id: Owner of the reading plans.

    Returns:
        Sync state for all of the user's release sources, enabled or disabled.
    """
    sources = await repo.list_for_user(db, user_id=user_id)
    return [
        SyncSourceStatus(
            source_id=source.id,
            plan_id=source.plan_id,
            thread_id=source.thread_id,
            external_identity_id=source.external_identity_id,
            provider_volume_id=source.external_identity.external_id,
            enabled=source.enabled,
            last_synced_at=source.last_synced_at,
        )
        for source in sources
    ]


@dataclass(frozen=True, slots=True)
class SourceFailure:
    """One source that could not be evaluated during a sync run."""

    source_id: int
    plan_id: int
    thread_id: int
    volume_id: int
    error: str


@dataclass(frozen=True, slots=True)
class SourceSyncResult:
    """Result of evaluating one release source."""

    source_id: int
    plan_id: int
    thread_id: int
    volume_id: int
    success: bool
    issues_checked: int = 0
    issues_created: int = 0
    issues_reused: int = 0
    future_skips: int = 0
    unknown_date_skips: int = 0
    conflicts: int = 0
    issue_failures: int = 0
    excluded: bool = False
    skipped: bool = False
    excluded_issues: int = 0
    error: str | None = None


@dataclass(slots=True)
class SyncReport:
    """Structured counters for one sync run."""

    total_sources: int
    enabled_sources: int
    checked_sources: int = 0
    successful_sources: int = 0
    failed_sources: int = 0
    issues_checked: int = 0
    created_issues: int = 0
    reused_issues: int = 0
    future_skips: int = 0
    unknown_date_skips: int = 0
    conflicts: int = 0
    issue_failures: int = 0
    excluded_sources: int = 0
    skipped_sources: int = 0
    excluded_issues: int = 0
    failures: list[SourceFailure] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Report whether the run completed without any source or issue failure."""
        return self.failed_sources == 0 and self.issue_failures == 0


@dataclass(frozen=True, slots=True)
class ScheduledUserFailure:
    """One owner whose sync could not be completed during a scheduled run."""

    user_id: int
    error: str


@dataclass(slots=True)
class ScheduledSyncReport:
    """Structured result of one scheduled (Vercel Cron) release-sync run.

    ``status`` is machine-readable. ``already_running`` is a successful no-op:
    another invocation holds the durable advisory lock, so this request did no
    work and must not be treated as an error by the caller.
    """

    status: Literal["completed", "already_running"]
    as_of: datetime
    users_total: int = 0
    users_processed: int = 0
    users_failed: int = 0
    users_deferred: int = 0
    truncated: bool = False
    duration_ms: int = 0
    total_sources: int = 0
    enabled_sources: int = 0
    checked_sources: int = 0
    successful_sources: int = 0
    failed_sources: int = 0
    issues_checked: int = 0
    created_issues: int = 0
    reused_issues: int = 0
    future_skips: int = 0
    unknown_date_skips: int = 0
    conflicts: int = 0
    issue_failures: int = 0
    excluded_sources: int = 0
    skipped_sources: int = 0
    excluded_issues: int = 0
    failures: list[SourceFailure] = field(default_factory=list)
    user_failures: list[ScheduledUserFailure] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Report whether the scheduled run completed without failures.

        An ``already_running`` no-op is successful: the overlapping invocation
        is already doing the work. A truncated run is not successful because
        some owners were not evaluated.
        """
        if self.status == "already_running":
            return True
        return (
            not self.truncated
            and self.users_failed == 0
            and self.failed_sources == 0
            and self.issue_failures == 0
        )


def _elapsed_ms(started_at: float) -> int:
    """Return whole milliseconds elapsed since a ``time.monotonic`` reading.

    Args:
        started_at: Monotonic start timestamp.

    Returns:
        Elapsed milliseconds, never negative.
    """
    return max(0, int((time.monotonic() - started_at) * 1000))


def _merge_user_report(report: ScheduledSyncReport, user_report: SyncReport) -> None:
    """Fold one owner's sync report into the scheduled run counters.

    Args:
        report: Mutable scheduled-run report.
        user_report: Per-owner report from :func:`sync_released_issues`.
    """
    report.total_sources += user_report.total_sources
    report.enabled_sources += user_report.enabled_sources
    report.checked_sources += user_report.checked_sources
    report.successful_sources += user_report.successful_sources
    report.failed_sources += user_report.failed_sources
    report.issues_checked += user_report.issues_checked
    report.created_issues += user_report.created_issues
    report.reused_issues += user_report.reused_issues
    report.future_skips += user_report.future_skips
    report.unknown_date_skips += user_report.unknown_date_skips
    report.conflicts += user_report.conflicts
    report.issue_failures += user_report.issue_failures
    report.excluded_sources += user_report.excluded_sources
    report.skipped_sources += user_report.skipped_sources
    report.excluded_issues += user_report.excluded_issues
    report.failures.extend(user_report.failures)


async def run_scheduled_release_sync(
    db: AsyncSession,
    *,
    as_of: datetime | None = None,
    refresh: bool = True,
    client: ComicVineClient | None = None,
    client_factory: Callable[[], ComicVineClient] | None = None,
    now: Callable[[], datetime] | None = None,
    max_duration_seconds: float = DEFAULT_CRON_MAX_DURATION_SECONDS,
) -> ScheduledSyncReport:
    """Run release-source sync for every owner with enabled sources.

    This is the scheduled (Vercel Cron) entry point. It owns no provider or
    adoption logic: each owner is delegated to :func:`sync_released_issues`,
    which already enforces per-owner collection exclusions, confirmed-volume
    identity checks, deterministic release gating, and per-source failure
    isolation.

    Concurrency is coordinated with a transaction-scoped PostgreSQL advisory
    lock so independent serverless instances cannot run the same scheduled sync
    at once. When the lock is already held, the second invocation returns an
    ``already_running`` no-op without touching provider or reader data.

    One owner's unexpected failure is rolled back to its own savepoint and
    recorded, so it cannot roll back work already completed for earlier owners.

    Args:
        db: Database session. The caller owns the transaction; this function
            flushes writes but never commits.
        as_of: Explicit UTC release boundary. Defaults to the current instant.
        refresh: Force live provider requests instead of the provider cache.
        client: Pre-built provider client shared across owners. Tests inject a
            fake here.
        client_factory: Builds the provider client when ``client`` is omitted.
        now: Supplies the default boundary and ``last_synced_at`` instants so
            tests stay deterministic.
        max_duration_seconds: Wall-clock budget for starting new owners. A
            non-positive value disables the budget.

    Returns:
        A :class:`ScheduledSyncReport` with machine-readable status and
        aggregate counters.
    """
    started_at = time.monotonic()
    clock = now or (lambda: datetime.now(UTC))
    boundary = _as_aware_utc(as_of) if as_of is not None else clock()
    report = ScheduledSyncReport(status="completed", as_of=boundary)

    lock_acquired = bool(
        await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": RELEASE_SYNC_CRON_LOCK_KEY},
        )
    )
    if not lock_acquired:
        report.status = "already_running"
        report.duration_ms = _elapsed_ms(started_at)
        logger.info("release_sync_cron_already_running duration_ms=%s", report.duration_ms)
        return report

    user_ids = await repo.list_enabled_user_ids(db)
    report.users_total = len(user_ids)

    resolved_client = client
    if resolved_client is None and user_ids:
        factory = client_factory if client_factory is not None else build_comicvine_client
        try:
            resolved_client = factory()
        except ValueError as error:
            message = str(error)
            logger.warning("release_sync_cron_client_unavailable error=%s", message)
            report.users_failed = len(user_ids)
            report.user_failures = [
                ScheduledUserFailure(user_id=user_id, error=message)
                for user_id in user_ids
            ]
            report.duration_ms = _elapsed_ms(started_at)
            logger.info(
                "release_sync_cron_completed status=%s users_total=%s users_processed=%s "
                "users_failed=%s users_deferred=%s truncated=%s duration_ms=%s",
                report.status,
                report.users_total,
                report.users_processed,
                report.users_failed,
                report.users_deferred,
                report.truncated,
                report.duration_ms,
            )
            return report

    deadline = (
        started_at + max_duration_seconds if max_duration_seconds > 0 else None
    )

    for index, user_id in enumerate(user_ids):
        if deadline is not None and time.monotonic() >= deadline:
            report.truncated = True
            report.users_deferred = len(user_ids) - index
            logger.warning(
                "release_sync_cron_time_budget_exhausted deferred=%s duration_ms=%s",
                report.users_deferred,
                _elapsed_ms(started_at),
            )
            break
        try:
            async with db.begin_nested():
                user_report = await sync_released_issues(
                    db,
                    user_id=user_id,
                    as_of=boundary,
                    refresh=refresh,
                    client=resolved_client,
                    now=clock,
                )
        except Exception as error:  # one owner must not abort the scheduled run
            logger.warning(
                "release_sync_cron_user_failed user_id=%s error=%s",
                user_id,
                error,
            )
            report.users_failed += 1
            report.user_failures.append(
                ScheduledUserFailure(
                    user_id=user_id,
                    error=f"User sync failed: {error}",
                )
            )
            continue

        report.users_processed += 1
        _merge_user_report(report, user_report)

    report.duration_ms = _elapsed_ms(started_at)
    logger.info(
        "release_sync_cron_completed status=%s users_total=%s users_processed=%s "
        "users_failed=%s users_deferred=%s truncated=%s sources_checked=%s "
        "sources_successful=%s sources_failed=%s created=%s reused=%s "
        "future_skips=%s unknown_date_skips=%s conflicts=%s issue_failures=%s "
        "excluded_sources=%s excluded_issues=%s duration_ms=%s",
        report.status,
        report.users_total,
        report.users_processed,
        report.users_failed,
        report.users_deferred,
        report.truncated,
        report.checked_sources,
        report.successful_sources,
        report.failed_sources,
        report.created_issues,
        report.reused_issues,
        report.future_skips,
        report.unknown_date_skips,
        report.conflicts,
        report.issue_failures,
        report.excluded_sources,
        report.excluded_issues,
        report.duration_ms,
    )
    return report


def _issue_identity(row: dict[str, object]) -> str | None:
    """Extract the canonical ComicVine issue identity from a roster row.

    Args:
        row: One provider roster row.

    Returns:
        The provider issue id as a string, or None when the row has no usable id.
    """
    raw = row.get("id")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _issue_number(row: dict[str, object]) -> str | None:
    """Extract the ComicVine issue number from a roster row.

    Args:
        row: One provider roster row.

    Returns:
        The verbatim issue number, or None when absent or blank.
    """
    raw = row.get("issue_number")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


async def sync_released_issues(
    db: AsyncSession,
    *,
    user_id: int,
    as_of: datetime,
    refresh: bool = True,
    client: ComicVineClient | None = None,
    client_factory: Callable[[], ComicVineClient] | None = None,
    now: Callable[[], datetime] | None = None,
) -> SyncReport:
    """Sync the user's followed ComicVine volumes and adopt released issues.

    Args:
        db: Database session. The caller owns the transaction; this service
            flushes its own writes but never commits, matching the layering
            standard that services do not own the request transaction.
        user_id: Owner of the release sources to sync.
        as_of: Explicit UTC release boundary. Issues with a ``store_date``
            after this instant are treated as unreleased solicitations.
        refresh: Force live provider requests instead of the cache.
        client: Pre-built provider client. Tests inject a fake here.
        client_factory: Builds the provider client when ``client`` is omitted.
            Resolved at call time so tests can substitute the default factory.
        now: Supplies the ``last_synced_at`` instant, so tests stay deterministic.

    Returns:
        A :class:`SyncReport` with per-run counters and bounded failures.
    """
    all_sources = await repo.list_for_user(db, user_id=user_id)
    enabled_sources = await repo.list_enabled_for_user(db, user_id=user_id)

    report = SyncReport(
        total_sources=len(all_sources),
        enabled_sources=len(enabled_sources),
    )

    if not enabled_sources:
        logger.info("reading_plan_sync_no_enabled_sources user_id=%s", user_id)
        return report

    boundary = _as_aware_utc(as_of)
    clock = now or (lambda: datetime.now(UTC))

    resolved_client = client
    if resolved_client is None:
        factory = client_factory if client_factory is not None else build_comicvine_client
        try:
            resolved_client = factory()
        except ValueError as error:
            message = str(error)
            logger.warning("reading_plan_sync_client_unavailable error=%s", message)
            for source in enabled_sources:
                report.failed_sources += 1
                report.failures.append(
                    SourceFailure(
                        source_id=source.id,
                        plan_id=source.plan_id,
                        thread_id=source.thread_id,
                        volume_id=_safe_volume_id(source),
                        error=message,
                    )
                )
            return report

    # Group by provider volume so one roster fetch serves every source that
    # follows the same volume, regardless of how many plans subscribe to it.
    # A source with a corrupt volume id is isolated as a failure instead of
    # aborting every other source in the run.
    volume_groups: dict[int, list[ReadingPlanReleaseSource]] = {}
    for source in enabled_sources:
        try:
            volume_key = _volume_id(source)
        except ValueError as error:
            report.failed_sources += 1
            report.failures.append(
                SourceFailure(
                    source_id=source.id,
                    plan_id=source.plan_id,
                    thread_id=source.thread_id,
                    volume_id=_UNKNOWN_VOLUME_ID,
                    error=str(error),
                )
            )
            continue
        volume_groups.setdefault(volume_key, []).append(source)

    synced_source_ids: list[int] = []

    for volume_id, sources in volume_groups.items():
        try:
            roster = await resolved_client.fetch_volume_issues(volume_id, refresh=refresh)
        except Exception as error:  # one volume must not abort the run
            logger.warning(
                "reading_plan_sync_volume_failed volume_id=%s error=%s",
                volume_id,
                error,
            )
            for source in sources:
                report.failed_sources += 1
                report.failures.append(
                    SourceFailure(
                        source_id=source.id,
                        plan_id=source.plan_id,
                        thread_id=source.thread_id,
                        volume_id=volume_id,
                        error=f"Volume sync failed: {error}",
                    )
                )
            continue

        report.checked_sources += len(sources)
        for source in sources:
            try:
                result = await _sync_source(
                    db,
                    source=source,
                    volume_id=volume_id,
                    roster=roster,
                    boundary=boundary,
                    client=resolved_client,
                )
            except Exception as error:  # one source must not abort the run
                logger.warning(
                    "reading_plan_sync_source_failed source_id=%s error=%s",
                    source.id,
                    error,
                )
                result = SourceSyncResult(
                    source_id=source.id,
                    plan_id=source.plan_id,
                    thread_id=source.thread_id,
                    volume_id=volume_id,
                    success=False,
                    error=f"Source sync failed: {error}",
                )
            _accumulate(report, result)
            if result.success and not result.skipped:
                synced_source_ids.append(result.source_id)

    synced_at = clock()
    for source_id in synced_source_ids:
        try:
            await repo.mark_synced(db, source_id=source_id, synced_at=synced_at)
        except Exception as error:  # bookkeeping must not abort the run
            logger.warning(
                "reading_plan_sync_last_synced_update_failed source_id=%s error=%s",
                source_id,
                error,
            )

    logger.info(
        "reading_plan_sync_completed user_id=%s checked=%s successful=%s failed=%s "
        "created=%s reused=%s future_skips=%s unknown_date_skips=%s conflicts=%s "
        "issue_failures=%s excluded_sources=%s excluded_issues=%s skipped_sources=%s",
        user_id,
        report.checked_sources,
        report.successful_sources,
        report.failed_sources,
        report.created_issues,
        report.reused_issues,
        report.future_skips,
        report.unknown_date_skips,
        report.conflicts,
        report.issue_failures,
        report.excluded_sources,
        report.excluded_issues,
        report.skipped_sources,
    )
    return report


def _volume_id(source: ReadingPlanReleaseSource) -> int:
    """Return the provider volume id carried by a release source.

    Args:
        source: Release source with an eagerly loaded external identity.

    Returns:
        The ComicVine volume id.

    Raises:
        ValueError: When the stored provider volume id is not an integer.
    """
    raw = str(source.external_identity.external_id).strip()
    try:
        return comicvine_volume_id(raw)
    except ValueError as error:
        raise ValueError(
            f"Release source {source.id} has a non-numeric ComicVine volume id: {raw!r}"
        ) from error


def _safe_volume_id(source: ReadingPlanReleaseSource) -> int:
    """Return the provider volume id for failure reporting, never raising.

    Args:
        source: Release source with an eagerly loaded external identity.

    Returns:
        The ComicVine volume id, or ``_UNKNOWN_VOLUME_ID`` when it is not numeric.
    """
    try:
        return _volume_id(source)
    except ValueError:
        return _UNKNOWN_VOLUME_ID


def _accumulate(report: SyncReport, result: SourceSyncResult) -> None:
    """Fold one source result into the run-level counters.

    Args:
        report: Mutable run report.
        result: Per-source outcome.
    """
    if not result.success:
        report.failed_sources += 1
        report.failures.append(
            SourceFailure(
                source_id=result.source_id,
                plan_id=result.plan_id,
                thread_id=result.thread_id,
                volume_id=result.volume_id,
                error=result.error or "Source sync failed",
            )
        )
        return

    report.excluded_sources += int(result.excluded)
    report.skipped_sources += int(result.skipped)
    report.excluded_issues += result.excluded_issues
    report.successful_sources += 1
    report.issues_checked += result.issues_checked
    report.created_issues += result.issues_created
    report.reused_issues += result.issues_reused
    report.future_skips += result.future_skips
    report.unknown_date_skips += result.unknown_date_skips
    report.conflicts += result.conflicts
    report.issue_failures += result.issue_failures


async def _sync_source(
    db: AsyncSession,
    *,
    source: ReadingPlanReleaseSource,
    volume_id: int,
    roster: list[dict[str, object]],
    boundary: datetime,
    client: ComicVineClient,
) -> SourceSyncResult:
    """Evaluate one release source against a fetched provider roster.

    Args:
        db: Database session.
        source: Release source to sync.
        volume_id: Provider volume id for the fetched roster.
        roster: Provider issue rows for that volume.
        boundary: UTC release boundary.
        client: Provider client used for optional metadata hydration.

    Returns:
        A :class:`SourceSyncResult` describing the source outcome.
    """
    owner_id = source.reading_plan.user_id
    source_id, plan_id, thread_id = source.id, source.plan_id, source.thread_id
    await lock_reader(db, owner_id)
    # Lock Thread before subscription rows so Thread deletion and its cascading
    # source deletion cannot deadlock or resurrect a stale target.
    thread = await thread_repository.lock_thread(db, thread_id)
    current = await repo.get_current_for_sync(db, source_id=source_id, user_id=owner_id)
    if thread is None or current is None or not current.enabled:
        return SourceSyncResult(source_id, plan_id, thread_id, volume_id, success=True, skipped=True)
    source = current
    plan = source.reading_plan
    if (_volume_id(source) != volume_id or source.thread_id != thread_id
        or source.plan_id != plan_id):
        return SourceSyncResult(source_id, plan_id, thread_id, volume_id, success=False,
                                error="Release source changed during provider fetch; retry")
    exclusions = await load_release_exclusions(db, owner_id)
    if exclusions.excludes_source(thread_id, volume_id):
        return SourceSyncResult(source_id, plan_id, thread_id, volume_id, success=True,
                                skipped=True, excluded=True)

    if thread is None or thread.user_id != plan.user_id:
        return SourceSyncResult(
            source_id=source.id,
            plan_id=source.plan_id,
            thread_id=source.thread_id,
            volume_id=volume_id,
            success=False,
            error=(
                f"Thread {source.thread_id} is not owned by plan {source.plan_id}'s user"
            ),
        )

    confirmed = await repo.has_confirmed_thread_volume(
        db,
        thread_id=source.thread_id,
        external_identity_id=source.external_identity_id,
    )
    if not confirmed:
        return SourceSyncResult(
            source_id=source.id,
            plan_id=source.plan_id,
            thread_id=source.thread_id,
            volume_id=volume_id,
            success=False,
            error=(
                f"Volume {volume_id} is no longer a confirmed ComicVine mapping "
                f"for thread {source.thread_id}"
            ),
        )

    issues_checked = 0
    issues_created = 0
    issues_reused = 0
    future_skips = 0
    unknown_date_skips = 0
    conflicts = 0
    issue_failures = 0
    excluded_issues = 0

    for row in roster:
        issues_checked += 1
        issue_id = _issue_identity(row)
        if issue_id is None:
            issue_failures += 1
            logger.warning(
                "reading_plan_sync_issue_missing_identity source_id=%s", source.id
            )
            continue

        store_date = parse_store_date(row.get("store_date"))
        if store_date is None:
            # Never infer release from cover_date or issue number.
            unknown_date_skips += 1
            continue
        if store_date > boundary:
            future_skips += 1
            continue

        issue_number = _issue_number(row)
        if issue_number is None:
            issue_failures += 1
            logger.warning(
                "reading_plan_sync_issue_missing_number source_id=%s issue_id=%s",
                source.id,
                issue_id,
            )
            continue

        existing = await issue_repository.find_owned_issue_by_confirmed_identity(
            db, owner_id, provider=COMICVINE_PROVIDER, external_id=issue_id,
        )
        if existing is None:
            existing = await issue_repository.find_in_thread_by_number(db, thread_id, issue_number)
        if existing is not None and (
            existing.id in exclusions.issue_ids or existing.thread_id in exclusions.thread_ids
        ):
            excluded_issues += 1
            continue
        try:
            adoption = await adopt_comicvine_issue(
                db,
                user_id=plan.user_id,
                thread_id=source.thread_id,
                comicvine_issue_id=int(issue_id),
                issue_number=issue_number,
                external_url=_external_url(row, issue_id),
                metadata=_issue_metadata(row),
                comicvine_client=client,
                thread=thread,
            )
        except Exception as error:  # one issue must not abort the source
            issue_failures += 1
            logger.warning(
                "reading_plan_sync_issue_failed source_id=%s issue_id=%s error=%s",
                source.id,
                issue_id,
                error,
            )
            continue

        if adoption.outcome == "created":
            issues_created += 1
        elif adoption.outcome == "reused":
            issues_reused += 1
        else:
            conflicts += 1

        # #3118: extend every plan following this source with the adopted issue.
        if adoption.outcome in ("created", "reused") and adoption.issue_id:
            from app.services.reading_plan_release_extension import (
                extend_plans_with_issue,
            )

            try:
                await extend_plans_with_issue(
                    db,
                    issue_id=adoption.issue_id,
                    source_id=source.id,
                    user_id=owner_id,
                    store_date=store_date,
                )
            except Exception as error:
                logger.warning(
                    "reading_plan_sync_extend_failed source_id=%s issue_id=%s error=%s",
                    source.id,
                    adoption.issue_id,
                    error,
                )

    return SourceSyncResult(
        source_id=source.id,
        plan_id=source.plan_id,
        thread_id=source.thread_id,
        volume_id=volume_id,
        success=True,
        issues_checked=issues_checked,
        issues_created=issues_created,
        issues_reused=issues_reused,
        future_skips=future_skips,
        unknown_date_skips=unknown_date_skips,
        conflicts=conflicts,
        issue_failures=issue_failures,
        excluded_issues=excluded_issues,
    )


def _external_url(row: dict[str, object], issue_id: str) -> str | None:
    """Build the canonical ComicVine issue URL for a roster row.

    Args:
        row: One provider roster row.
        issue_id: Canonical provider issue id.

    Returns:
        The provider issue URL, or None when the row omits one.
    """
    raw = row.get("site_detail_url")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return f"https://comicvine.gamespot.com/issue/4000-{issue_id}/"


def _issue_metadata(row: dict[str, object]) -> dict[str, object]:
    """Collect trusted provider facts worth storing on first identity creation.

    Args:
        row: One provider roster row.

    Returns:
        A metadata mapping limited to fields the provider actually returned.
    """
    metadata: dict[str, object] = {}
    for key in ("name", "issue_number", "cover_date", "store_date", "date_last_updated"):
        value = row.get(key)
        if value is not None:
            metadata[key] = value
    volume = row.get("volume")
    if isinstance(volume, dict):
        volume_name = volume.get("name")
        if isinstance(volume_name, str) and volume_name.strip():
            metadata["volume_name"] = volume_name.strip()
    return metadata