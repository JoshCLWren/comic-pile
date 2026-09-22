r"""Local-first ComicVine read backfill operator for identity resolution and creator hydration.

Single documented operator command::

    python scripts/backfill_read_comicvine.py --user-id 1 \\
        --database-url postgresql+asyncpg://user:pass@localhost/comicpile \\
        --comicvine-db /data/comicvine.sqlite --report-path /tmp/backfill-report.json

The pipeline exhausts local evidence before live provider work, paces live
request starts, isolates per-resource throttle cooldowns, stays resumable via
per-issue commits, and always emits a machine-readable JSON report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.comicvine_hydration import hydrate_issue
from app.external_identities import upsert_external_identity
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.comicvine_identity_repair import ComicVineRepairContext
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError, ComicVineRateLimitError
from comic_pile.comicvine_repair_pipeline import repair_identity
from comic_pile.local_comicvine import LocalComicVineSnapshot

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_IDENTITY_RESOURCE = "search"
_CREATOR_RESOURCE = "issue"

_THROTTLE_BASE_SECONDS = 60.0
_THROTTLE_MAX_SECONDS = 3600.0


def _normalize_issue_label(value: object) -> str:
    """Normalize an issue number or human label for comparison.

    Args:
        value: Raw issue label from ComicPile or provider metadata.

    Returns:
        Lowercased, NFKC-normalized label with any leading hash removed.
    """
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().removeprefix("#").strip().split())


def _provider_issue_id(external_id: str) -> int | None:
    """Extract the numeric ComicVine issue ID from a stored external ID.

    Args:
        external_id: Stored provider external ID, optionally ``4000-`` prefixed.

    Returns:
        The integer ComicVine issue ID, or None when not numeric.
    """
    normalized = external_id.removeprefix("4000-").strip()
    return int(normalized) if normalized.isdigit() else None


def _identity_matches_issue(identity: ExternalIdentity, issue_number: str) -> bool:
    """Return whether an external issue identity matches one ComicPile issue label.

    Args:
        identity: External ComicVine issue identity.
        issue_number: ComicPile issue number label to match.

    Returns:
        True when the stored label (issue number or issue name) matches.
    """
    expected = _normalize_issue_label(issue_number)
    if not expected:
        return False
    metadata = identity.metadata_json or {}
    return any(
        _normalize_issue_label(metadata.get(key)) == expected
        for key in ("issue_number", "name")
    )


class ThrottleResourceSnapshot(TypedDict):
    """Snapshot of a single resource's throttle state."""

    cooling: bool
    cooldown_remaining_seconds: float
    consecutive_throttles: int


class ThrottleSnapshot(TypedDict):
    """Full throttle snapshot mapping resource names to their state."""

    search: ThrottleResourceSnapshot
    issue: ThrottleResourceSnapshot


class BackfillReport(TypedDict):
    """Machine-readable backfill report."""

    user_id: int
    dry_run: bool
    requests_per_hour: int
    local_snapshot_available: bool
    total_issues: int
    resolved_identities: int
    resolved_creators: int
    unresolved_identities: int
    unresolved_creators: int
    rate_limited: int
    errors: int
    skipped_existing: int
    completion_rate: float
    throttles: dict[str, ThrottleResourceSnapshot]
    completed_at: str


@dataclass
class BackfillStats:
    """Execution statistics for the backfill operation."""

    total_issues: int = 0
    resolved_identities: int = 0
    resolved_creators: int = 0
    unresolved_identities: int = 0
    unresolved_creators: int = 0
    rate_limited: int = 0
    errors: int = 0
    skipped_existing: int = 0

    @property
    def completion_rate(self) -> float:
        """Calculate completion rate as a percentage."""
        if self.total_issues == 0:
            return 0.0
        return ((self.resolved_identities + self.resolved_creators) / self.total_issues) * 100


@dataclass
class BackfillProgress:
    """Real-time progress tracking for the backfill operation."""

    current_issue: int = 0
    current_phase: Literal["identity", "creator"] = "identity"
    stats: BackfillStats = field(default_factory=BackfillStats)
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_update: datetime = field(default_factory=lambda: datetime.now(UTC))

    def update(self, issue_id: int, phase: Literal["identity", "creator"], status: str) -> None:
        """Update progress for a single issue."""
        self.current_issue = issue_id
        self.current_phase = phase
        self.last_update = datetime.now(UTC)

        normalized = status
        if status == "resolved":
            normalized = f"resolved_{phase}"
        elif status == "unresolved":
            normalized = f"unresolved_{phase}"

        if normalized == "resolved_identity":
            self.stats.resolved_identities += 1
        elif normalized == "resolved_creator":
            self.stats.resolved_creators += 1
        elif normalized == "unresolved_identity":
            self.stats.unresolved_identities += 1
        elif normalized == "unresolved_creator":
            self.stats.unresolved_creators += 1
        elif normalized == "rate_limited":
            self.stats.rate_limited += 1
        elif normalized == "error":
            self.stats.errors += 1
        elif normalized == "skipped":
            self.stats.skipped_existing += 1


class ResourceThrottleTracker:
    """Track per-resource ComicVine cooldowns with bounded fallback backoff.

    One throttled resource must not terminate unrelated satisfiable work, so
    cooldown state is kept per resource (for example ``search`` versus
    ``issue``). Backoff doubles from a one-minute base, is bounded at one
    hour, and resets on the next successful live request for that resource.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """Configure the tracker with an injectable clock for tests.

        Args:
            clock: Time source returning seconds; defaults to monotonic time.
        """
        self._clock = clock
        self._cooldown_until: dict[str, float] = {}
        self._consecutive_throttles: dict[str, int] = {}

    def cooling(self, resource: str) -> bool:
        """Return whether the resource is inside an active throttle cooldown."""
        return self._cooldown_until.get(resource, 0.0) > self._clock()

    def cooldown_remaining(self, resource: str) -> float:
        """Return remaining cooldown seconds for the resource, or 0.0."""
        return max(0.0, self._cooldown_until.get(resource, 0.0) - self._clock())

    def record_throttle(self, resource: str) -> float:
        """Record a throttle signal and return the applied cooldown in seconds.

        Args:
            resource: Throttled ComicVine resource bucket.

        Returns:
            Applied cooldown delay, bounded at one hour.
        """
        consecutive = self._consecutive_throttles.get(resource, 0) + 1
        self._consecutive_throttles[resource] = consecutive
        delay = min(_THROTTLE_MAX_SECONDS, _THROTTLE_BASE_SECONDS * (2.0 ** (consecutive - 1)))
        self._cooldown_until[resource] = self._clock() + delay
        return delay

    def record_success(self, resource: str) -> None:
        """Reset backoff state after a successful live request.

        Args:
            resource: ComicVine resource bucket that succeeded.
        """
        self._consecutive_throttles.pop(resource, None)
        self._cooldown_until.pop(resource, None)

    def snapshot(self) -> dict[str, ThrottleResourceSnapshot]:
        """Return machine-readable per-resource throttle state."""
        resources = sorted(set(self._cooldown_until) | set(self._consecutive_throttles))
        return {
            resource: {
                "cooling": self.cooling(resource),
                "cooldown_remaining_seconds": round(self.cooldown_remaining(resource), 3),
                "consecutive_throttles": self._consecutive_throttles.get(resource, 0),
            }
            for resource in resources
        }


class ComicVineBackfillOperator:
    """Production-safe ComicVine backfill operator with local-first resolution."""

    def __init__(
        self,
        user_id: int,
        database_url: str,
        cache_dir: Path,
        dry_run: bool = False,
        requests_per_hour: int = 180,
        comicvine_db: Path | None = None,
        report_path: Path | None = None,
        min_live_interval_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        """Initialize the backfill operator.

        Args:
            user_id: Target user ID for the backfill operation.
            database_url: Database connection URL (must be explicit, no .env loading).
            cache_dir: Directory for ComicVine cache persistence.
            dry_run: If True, only report what would be done.
            requests_per_hour: Rolling request ceiling per endpoint.
            comicvine_db: Optional local ComicVine SQLite snapshot; local evidence
                from it is exhausted before live calls when configured.
            report_path: Optional path for the machine-readable JSON report.
            min_live_interval_seconds: Minimum spacing between live request starts.
            clock: Time source for pacing and throttle backoff.
        """
        self.user_id = user_id
        self.database_url = database_url
        self.cache_dir = cache_dir
        self.dry_run = dry_run
        self.requests_per_hour = requests_per_hour
        self.report_path = report_path
        self.min_live_interval_seconds = min_live_interval_seconds
        self._clock = clock
        self._last_live_start = 0.0

        self.snapshot = LocalComicVineSnapshot(comicvine_db)
        self.throttles = ResourceThrottleTracker(clock=clock)

        # Initialize ComicVine client if not in dry run mode
        self.client: ComicVineClient | None = None
        if not dry_run:
            api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("COMICVINE_API_KEY is required for live backfill operations")
            self.client = ComicVineClient(api_key, cache_dir, requests_per_hour=requests_per_hour)

        # Progress tracking
        self.progress = BackfillProgress()

    async def get_read_issues(self, db: AsyncSession) -> list[Issue]:
        """Get all read issues for the target user that need backfill processing.

        Args:
            db: Async database session.

        Returns:
            List of read issues that need processing.
        """
        result = await db.execute(
            select(Issue)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(
                Thread.user_id == self.user_id,
                Issue.status == "read",
                # Exclude issues that already have confirmed ComicVine identities
                ~Issue.id.in_(
                    select(IssueExternalIdentityMapping.issue_id).join(
                        ExternalIdentity,
                        ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
                    ).where(
                        ExternalIdentity.provider == "comicvine",
                        IssueExternalIdentityMapping.status == "confirmed",
                    )
                ),
            )
            .order_by(Thread.queue_position, Issue.position)
        )
        return result.scalars().all()

    async def resolve_identity_locally(self, db: AsyncSession, issue: Issue) -> ExternalIdentity | None:
        """Try to resolve ComicVine identity using local evidence only.

        Args:
            db: Async database session.
            issue: Issue to resolve.

        Returns:
            Resolved external identity if found locally, None otherwise.
        """
        # Check if thread has a confirmed series mapping
        series_result = await db.execute(
            select(ExternalIdentity)
            .join(
                ThreadExternalSeriesMapping,
                ThreadExternalSeriesMapping.external_identity_id == ExternalIdentity.id,
            )
            .where(
                ThreadExternalSeriesMapping.thread_id == issue.thread_id,
                ThreadExternalSeriesMapping.status == "confirmed",
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "series",
            )
            .order_by(
                ThreadExternalSeriesMapping.confidence.desc().nullslast(),
                ExternalIdentity.id,
            )
            .limit(1)
        )
        series_identity = series_result.scalar_one_or_none()

        if series_identity is None:
            return None

        metadata = series_identity.metadata_json or {}
        volume_id = metadata.get("volume_id")

        if volume_id is None:
            return None

        if self.snapshot.available and not await self._snapshot_corroborates_issue(
            volume_id, issue.issue_number
        ):
            return None

        # Look for existing issue mappings for this volume. Label equality is
        # enforced below so a same-volume identity with a different issue label
        # is never auto-confirmed.
        issue_result = await db.execute(
            select(ExternalIdentity)
            .join(
                IssueExternalIdentityMapping,
                IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
            )
            .where(
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "issue",
                cast(ExternalIdentity.metadata_json["volume_id"], String) == str(volume_id),
            )
            .limit(1)
        )
        identity = issue_result.scalar_one_or_none()
        if identity is None or not _identity_matches_issue(identity, issue.issue_number):
            return None
        return identity

    async def _snapshot_corroborates_issue(self, volume_id: object, issue_number: str) -> bool:
        """Check the local SQLite snapshot roster for one volume issue number.

        Args:
            volume_id: ComicVine volume ID from the confirmed series mapping.
            issue_number: ComicPile issue number label to corroborate.

        Returns:
            True when the local roster contains the issue label, False otherwise
            (including when the volume ID is unusable or the snapshot errors).
        """
        try:
            volume = int(volume_id) if not isinstance(volume_id, bool) else -1
        except (TypeError, ValueError):
            return False
        try:
            rows = await asyncio.to_thread(self.snapshot.get_volume_issues, volume)
        except Exception:
            # A damaged snapshot means "no local evidence", not a fatal error;
            # the caller falls through to the remaining local/provider paths.
            return False
        expected = (issue_number or "").strip().casefold().removeprefix("#").strip()
        for row in rows:
            for raw_label in (row.data.get("issue_number"), row.data.get("name")):
                if raw_label is None:
                    continue
                label = str(raw_label).strip().casefold().removeprefix("#").strip()
                if label and label == expected:
                    return True
        return False

    async def _confirm_issue_identity(
        self,
        db: AsyncSession,
        issue_id: int,
        external_identity_id: int,
        evidence_source: str,
    ) -> None:
        """Idempotently confirm one issue identity mapping via the ORM.

        Args:
            db: Async database session.
            issue_id: ComicPile issue ID.
            external_identity_id: Resolved external identity ID.
            evidence_source: Provenance label for the confirmation.
        """
        result = await db.execute(
            select(IssueExternalIdentityMapping).where(
                IssueExternalIdentityMapping.issue_id == issue_id,
                IssueExternalIdentityMapping.external_identity_id == external_identity_id,
            )
        )
        mapping = result.scalar_one_or_none()
        if mapping is None:
            db.add(
                IssueExternalIdentityMapping(
                    issue_id=issue_id,
                    external_identity_id=external_identity_id,
                    status="confirmed",
                    confidence=1.0,
                    evidence_source=evidence_source,
                    evidence_json={"resolution": evidence_source},
                )
            )
        else:
            mapping.status = "confirmed"
            mapping.confidence = 1.0
            mapping.evidence_source = evidence_source
        await db.flush()

    async def _pace_live_start(self) -> None:
        """Stagger live provider starts so a fresh run does not burst."""
        if self.min_live_interval_seconds <= 0:
            return
        wait = self.min_live_interval_seconds - (self._clock() - self._last_live_start)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_live_start = self._clock()

    async def resolve_identity_provider(self, db: AsyncSession, issue: Issue) -> ExternalIdentity | None:
        """Try to resolve ComicVine identity using local snapshot then live provider.

        Reuses the repair pipeline's conservative local-then-live candidate
        resolution so the backfill operator shares the same confidence gates as
        the interactive repair flow. Only a ``confirmed`` decision is promoted;
        ambiguous ``candidate`` outcomes stay unresolved and the mapping is never
        silently guessed.

        Args:
            db: Async database session.
            issue: Issue to resolve.

        Returns:
            Resolved external identity if confirmed, None otherwise.
        """
        client = self.client
        if client is None:
            return None

        thread = await db.get(Thread, issue.thread_id)
        if thread is None or not thread.title.strip():
            return None

        context = ComicVineRepairContext(
            title=thread.title,
            issue_label=issue.issue_number,
        )
        decision, _scores = await repair_identity(
            snapshot=self.snapshot,
            client=client,
            context=context,
            thread_issue_labels=[],
        )
        if decision.status != "confirmed" or decision.winner is None:
            return None

        candidate = decision.winner.candidate
        return await upsert_external_identity(
            db,
            provider="comicvine",
            entity_type="issue",
            external_id=f"4000-{candidate.issue_id}",
            external_url=f"https://comicvine.gamespot.com/issue/4000-{candidate.issue_id}/",
            metadata_json={
                "volume_id": candidate.volume_id,
                "volume_name": candidate.volume_name,
                "issue_number": candidate.issue_number,
                "name": candidate.issue_name,
            },
        )

    async def hydrate_creator_locally(self, db: AsyncSession, issue: Issue) -> bool:
        """Hydrate creator data using local evidence only.

        A confirmed issue identity whose stored metadata already carries creator
        credits (``creator_credits`` from the hydration path, or legacy
        ``person_credits``) is satisfied by stored evidence alone, so no live
        provider call is needed.

        Args:
            db: Async database session.
            issue: Issue to hydrate.

        Returns:
            True if creators were hydrated, False otherwise.
        """
        identity = await self._confirmed_issue_identity(db, issue)
        if identity is None:
            return False

        metadata = identity.metadata_json or {}
        credits = metadata.get("creator_credits") or metadata.get("person_credits")
        return bool(credits)

    async def hydrate_creator_provider(self, db: AsyncSession, issue: Issue) -> bool:
        """Deep-hydrate creator metadata for a confirmed issue identity.

        Fetches the full singular issue metadata (including creator credits)
        through the provider client and persists normalized creator metadata on
        the identity so later local passes read credits from storage.

        Args:
            db: Async database session.
            issue: Issue to hydrate.

        Returns:
            True if creators were hydrated, False otherwise.
        """
        client = self.client
        if client is None:
            return False

        identity = await self._confirmed_issue_identity(db, issue)
        if identity is None:
            return False

        comicvine_issue_id = _provider_issue_id(identity.external_id)
        if comicvine_issue_id is None:
            return False

        hydrated = await hydrate_issue(db, client, comicvine_issue_id)
        metadata = hydrated.metadata_json or {}
        credits = metadata.get("creator_credits") or metadata.get("person_credits")
        return bool(credits)

    async def _confirmed_issue_identity(self, db: AsyncSession, issue: Issue) -> ExternalIdentity | None:
        """Return the confirmed ComicVine issue identity for one issue.

        Args:
            db: Async database session.
            issue: Issue whose confirmed identity is requested.

        Returns:
            The confirmed identity, or None when no confirmed mapping exists.
        """
        result = await db.execute(
            select(ExternalIdentity)
            .join(
                IssueExternalIdentityMapping,
                IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
            )
            .where(
                IssueExternalIdentityMapping.issue_id == issue.id,
                IssueExternalIdentityMapping.status == "confirmed",
                ExternalIdentity.provider == "comicvine",
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def process_issue_identity(self, db: AsyncSession, issue: Issue) -> Literal["resolved", "unresolved", "rate_limited", "error"]:
        """Process identity resolution for a single issue.

        Local evidence (including the configured SQLite snapshot) is always
        attempted first. Live provider work for a cooling resource short
        circuits to ``rate_limited`` so unrelated work can continue.

        Args:
            db: Async database session.
            issue: Issue to process.

        Returns:
            Status of the identity resolution attempt.
        """
        try:
            # First try local resolution
            identity = await self.resolve_identity_locally(db, issue)
            if identity is not None:
                if not self.dry_run:
                    await self._confirm_issue_identity(
                        db, issue.id, identity.id, "local_resolution"
                    )
                return "resolved"

            # Then try provider resolution
            if self.client is not None:
                if self.throttles.cooling(_IDENTITY_RESOURCE):
                    return "rate_limited"
                try:
                    await self._pace_live_start()
                    identity = await self.resolve_identity_provider(db, issue)
                    if identity is not None:
                        if not self.dry_run:
                            await self._confirm_issue_identity(
                                db, issue.id, identity.id, "provider_resolution"
                            )
                        self.throttles.record_success(_IDENTITY_RESOURCE)
                        return "resolved"
                except ComicVineRateLimitError:
                    self.throttles.record_throttle(_IDENTITY_RESOURCE)
                    return "rate_limited"
                except ComicVineError:
                    return "error"

            return "unresolved"

        except Exception as exc:
            print(f"Error processing identity for issue {issue.id}: {exc}", file=sys.stderr)
            return "error"

    async def process_issue_creator(self, db: AsyncSession, issue: Issue) -> Literal["resolved", "unresolved", "rate_limited", "error"]:
        """Process creator hydration for a single issue.

        A cooling creator resource short circuits to ``rate_limited`` without
        blocking identity work for other issues.

        Args:
            db: Async database session.
            issue: Issue to process.

        Returns:
            Status of the creator hydration attempt.
        """
        try:
            # First try local hydration
            if await self.hydrate_creator_locally(db, issue):
                return "resolved"

            # Then try provider hydration
            if self.client is not None:
                if self.throttles.cooling(_CREATOR_RESOURCE):
                    return "rate_limited"
                try:
                    await self._pace_live_start()
                    if await self.hydrate_creator_provider(db, issue):
                        self.throttles.record_success(_CREATOR_RESOURCE)
                        return "resolved"
                except ComicVineRateLimitError:
                    self.throttles.record_throttle(_CREATOR_RESOURCE)
                    return "rate_limited"
                except ComicVineError:
                    return "error"

            return "unresolved"

        except Exception as exc:
            print(f"Error processing creator for issue {issue.id}: {exc}", file=sys.stderr)
            return "error"

    async def process_issue(self, db: AsyncSession, issue: Issue) -> None:
        """Process a single issue through both identity and creator phases.

        Args:
            db: Async database session.
            issue: Issue to process.
        """
        # Phase 1: Identity resolution
        identity_status = await self.process_issue_identity(db, issue)
        self.progress.update(issue.id, "identity", identity_status)

        # Only proceed to creator phase if identity was resolved
        if identity_status == "resolved":
            creator_status = await self.process_issue_creator(db, issue)
            self.progress.update(issue.id, "creator", creator_status)

    def build_report(self) -> BackfillReport:
        """Return a machine-readable summary of the backfill run.

        Returns:
            JSON-compatible report with progress statistics, per-resource
            throttle state, and local snapshot availability.
        """
        stats = self.progress.stats
        return {
            "user_id": self.user_id,
            "dry_run": self.dry_run,
            "requests_per_hour": self.requests_per_hour,
            "local_snapshot_available": self.snapshot.available,
            "total_issues": stats.total_issues,
            "resolved_identities": stats.resolved_identities,
            "resolved_creators": stats.resolved_creators,
            "unresolved_identities": stats.unresolved_identities,
            "unresolved_creators": stats.unresolved_creators,
            "rate_limited": stats.rate_limited,
            "errors": stats.errors,
            "skipped_existing": stats.skipped_existing,
            "completion_rate": round(stats.completion_rate, 1),
            "throttles": self.throttles.snapshot(),
            "completed_at": datetime.now(UTC).isoformat(),
        }

    async def _run_with_session_factory(self, session_factory: SessionFactory) -> None:
        """Process every outstanding read issue with per-issue commits.

        Per-issue commits keep the command idempotent and safely resumable
        after interruption.

        Args:
            session_factory: Factory producing async database sessions bound to
                the explicit operator database URL.
        """
        async with session_factory() as db:
            issues = await self.get_read_issues(db)
            total_count = len(issues)
            self.progress.stats.total_issues = total_count

            print(f"Found {total_count} read issues needing ComicVine backfill")
            print()

            for i, issue in enumerate(issues, 1):
                print(f"Processing issue {i}/{total_count} (ID: {issue.id})")

                await self.process_issue(db, issue)

                # Commit after each issue to maintain resumability
                await db.commit()

                # Report progress
                progress = self.progress
                print(
                    f"  Identity: {progress.stats.resolved_identities} resolved, "
                    f"{progress.stats.unresolved_identities} unresolved, "
                    f"{progress.stats.rate_limited} rate limited"
                )
                print(
                    f"  Creators: {progress.stats.resolved_creators} resolved, "
                    f"{progress.stats.unresolved_creators} unresolved"
                )
                print(f"  Completion: {progress.stats.completion_rate:.1f}%")
                print()

    async def run(self, session_factory: SessionFactory | None = None) -> BackfillStats:
        """Execute the complete backfill operation.

        Args:
            session_factory: Optional session factory for tests. Production
                always builds sessions from the explicit ``database_url`` so no
                ambient configuration is loaded.

        Returns:
            Final statistics for the operation.
        """
        print(f"Starting ComicVine backfill for user {self.user_id}")
        print(f"Database: {self.database_url}")
        print(f"Cache directory: {self.cache_dir}")
        print(f"Dry run: {self.dry_run}")
        print(f"Requests per hour: {self.requests_per_hour}")
        print(f"Local snapshot available: {self.snapshot.available}")
        print()

        if session_factory is None:
            engine = create_async_engine(self.database_url)
            try:
                await self._run_with_session_factory(
                    async_sessionmaker(engine, expire_on_commit=False)
                )
            finally:
                await engine.dispose()
        else:
            await self._run_with_session_factory(session_factory)

        # Final report
        stats = self.progress.stats
        print("Backfill completed!")
        print(f"Total issues processed: {stats.total_issues}")
        print(f"Identities resolved: {stats.resolved_identities}")
        print(f"Creators resolved: {stats.resolved_creators}")
        print(f"Identities unresolved: {stats.unresolved_identities}")
        print(f"Creators unresolved: {stats.unresolved_creators}")
        print(f"Rate limited: {stats.rate_limited}")
        print(f"Errors: {stats.errors}")
        print(f"Skipped (already complete): {stats.skipped_existing}")
        print(f"Final completion rate: {stats.completion_rate:.1f}%")

        report = self.build_report()
        print(json.dumps(report, indent=2, sort_keys=True))
        if self.report_path is not None:
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
            )

        return stats


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed CLI arguments.
    """
    parser = argparse.ArgumentParser(
        description="Local-first ComicVine read backfill operator for identity resolution and creator hydration",
    )
    parser.add_argument("--user-id", type=int, required=True, help="Target user ID for backfill")
    parser.add_argument(
        "--database-url",
        type=str,
        required=True,
        help="Database connection URL (explicit, no .env loading)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/tmp/comicpile-comicvine"),
        help="Directory for ComicVine cache persistence",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be done without making changes",
    )
    parser.add_argument(
        "--requests-per-hour",
        type=int,
        default=180,
        help="Rolling request ceiling per endpoint (default: 180)",
    )
    parser.add_argument(
        "--comicvine-db",
        type=Path,
        default=None,
        help="Optional local ComicVine SQLite snapshot; local evidence from it is "
        "exhausted before live calls when configured",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="Optional path for the machine-readable JSON report",
    )
    parser.add_argument(
        "--min-live-interval-seconds",
        type=float,
        default=1.0,
        help="Minimum spacing between live request starts (default: 1.0)",
    )

    return parser.parse_args()


def main() -> None:
    """Run the ComicVine backfill operator."""
    args = parse_args()
    
    try:
        operator = ComicVineBackfillOperator(
            user_id=args.user_id,
            database_url=args.database_url,
            cache_dir=args.cache_dir,
            dry_run=args.dry_run,
            requests_per_hour=args.requests_per_hour,
            comicvine_db=args.comicvine_db,
            report_path=args.report_path,
            min_live_interval_seconds=args.min_live_interval_seconds,
        )

        asyncio.run(operator.run())
            
    except Exception as exc:
        print(f"Backfill failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()