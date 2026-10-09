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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.repositories import reading_plan_release_source_repository as repo
from app.services.provider_issue_adoption import adopt_comicvine_issue
from comic_pile.comicvine_provider import ComicVineClient

logger = logging.getLogger(__name__)

COMICVINE_PROVIDER = "comicvine"

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
    failures: list[SourceFailure] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Report whether the run completed without any source or issue failure."""
        return self.failed_sources == 0 and self.issue_failures == 0


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
                        volume_id=_volume_id(source),
                        error=message,
                    )
                )
            return report

    # Group by provider volume so one roster fetch serves every source that
    # follows the same volume, regardless of how many plans subscribe to it.
    volume_groups: dict[int, list[ReadingPlanReleaseSource]] = {}
    for source in enabled_sources:
        volume_groups.setdefault(_volume_id(source), []).append(source)

    synced_source_ids: list[int] = []

    for volume_id, sources in volume_groups.items():
        try:
            roster = await resolved_client.fetch_volume_issues(volume_id, refresh=refresh)
        except Exception as error:  # noqa: BLE001 - one volume must not abort the run
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
            except Exception as error:  # noqa: BLE001 - one source must not abort the run
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
            if result.success:
                synced_source_ids.append(result.source_id)

    synced_at = clock()
    for source_id in synced_source_ids:
        try:
            await repo.mark_synced(db, source_id=source_id, synced_at=synced_at)
        except Exception as error:  # noqa: BLE001 - bookkeeping must not abort the run
            logger.warning(
                "reading_plan_sync_last_synced_update_failed source_id=%s error=%s",
                source_id,
                error,
            )

    logger.info(
        "reading_plan_sync_completed user_id=%s checked=%s successful=%s failed=%s "
        "created=%s reused=%s future_skips=%s unknown_date_skips=%s conflicts=%s "
        "issue_failures=%s",
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
        return int(raw)
    except ValueError as error:
        raise ValueError(
            f"Release source {source.id} has a non-numeric ComicVine volume id: {raw!r}"
        ) from error


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
    thread = source.thread
    plan = source.reading_plan

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
            )
        except Exception as error:  # noqa: BLE001 - one issue must not abort the source
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