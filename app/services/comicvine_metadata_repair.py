"""Durable ComicVine creator-metadata repair for confirmed issue identities.

Issue #4148: a correctly mapped Roll issue can still show no creators because
its stored metadata came from a sparse volume-roster row. Interactive reads
must stay fast and must not depend on a detached serverless task, so the read
path persists an idempotent request keyed by ``external_identity_id`` and a
bounded worker drains it later. The worker fetches the singular ComicVine issue
(never the cover filename), reuses the existing normalized hydrator, and leaves
confirmed mappings, ratings, and reading progress untouched.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.comicvine_hydration import hydrate_issue
from app.database import AsyncSessionLocal
from app.models.external_identity import ExternalIdentity
from app.repositories import comicvine_metadata_refresh_repository as refresh_repository
from app.services.comicvine_fallback import (
    COMICVINE_METADATA_MAX_AGE,
    metadata_needs_hydration,
)
from comic_pile.comicvine_provider import (
    DEEP_ISSUE_FIELDS,
    ComicVineClient,
    ComicVineError,
    ComicVineRateLimitError,
)

logger = logging.getLogger(__name__)

COMICVINE_REPAIR_MAX_ATTEMPTS = 3
"""Provider attempts allowed in one durable retry cycle."""

COMICVINE_REPAIR_LEASE_SECONDS = 120.0
"""How long one worker claim stays valid before another instance may resume it."""

COMICVINE_REPAIR_BACKOFF_SECONDS = (60.0, 300.0, 900.0)
"""Bounded backoff between provider attempts."""

COMICVINE_REPAIR_FAILED_COOLDOWN_SECONDS = 6 * 60 * 60.0
"""Cooldown before a later read may open a fresh retry cycle."""

COMICVINE_REPAIR_NOT_CONFIGURED_COOLDOWN_SECONDS = 6 * 60 * 60.0
"""How long to defer when ComicVine is not configured for this deployment."""

COMICVINE_REPAIR_DEFAULT_DRAIN_LIMIT = 3
COMICVINE_REPAIR_MAX_DRAIN_LIMIT = 10
COMICVINE_REPAIR_REQUEST_TIMEOUT_SECONDS = 5.0
COMICVINE_REPAIR_MIN_REQUEST_INTERVAL_SECONDS = 1.0

METADATA_STATUS_NOT_DEEP_FETCHED = "not_deep_fetched"
METADATA_STATUS_REFRESH_PENDING = "refresh_pending"
METADATA_STATUS_REFRESH_RUNNING = "refresh_running"
METADATA_STATUS_COMPLETE = "complete"
METADATA_STATUS_NO_CREDITS = "deep_fetched_no_credits"
METADATA_STATUS_REFRESH_DEFERRED = "refresh_deferred"
METADATA_STATUS_REFRESH_FAILED = "refresh_failed"

_DEEP_ISSUE_FIELDS = frozenset(DEEP_ISSUE_FIELDS)

_drain_task: asyncio.Task[None] | None = None


@dataclass(frozen=True, slots=True)
class MetadataRepairState:
    """Plain snapshot of one durable repair request for the read response."""

    state: str
    attempts: int
    next_attempt_at: datetime | None
    last_error: str | None
    refresh_requested: bool


@dataclass(frozen=True, slots=True)
class MetadataRepairDrainReport:
    """Bounded outcome counts from one worker drain."""

    claimed: int = 0
    completed: int = 0
    no_credits: int = 0
    deferred: int = 0
    failed: int = 0
    provider_configured: bool = True


def _normalized_timestamp(value: datetime) -> datetime:
    """Normalize a database timestamp to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def has_deep_issue_metadata(metadata: dict[str, object]) -> bool:
    """Return whether stored metadata came from a singular ComicVine response.

    Volume-roster rows omit the deep relationship fields, so a payload that
    contains all of them was produced by the singular issue endpoint.

    Args:
        metadata: Stored ``external_identities.metadata_json`` value.

    Returns:
        True when the raw provider payload carries every deep issue field.
    """
    raw_payload = metadata.get("raw_provider_payload")
    return isinstance(raw_payload, dict) and _DEEP_ISSUE_FIELDS.issubset(raw_payload)


def has_creator_credits(metadata: dict[str, object]) -> bool:
    """Return whether stored metadata carries any nonempty creator credit.

    Args:
        metadata: Stored ``external_identities.metadata_json`` value.

    Returns:
        True when a normalized or raw ``person_credits``/``creator_credits``
        array contains at least one entry.
    """
    for key in ("person_credits", "creator_credits"):
        value = metadata.get(key)
        if isinstance(value, list) and value:
            return True
    raw_payload = metadata.get("raw_provider_payload")
    if isinstance(raw_payload, dict):
        raw_credits = raw_payload.get("person_credits")
        if isinstance(raw_credits, list) and raw_credits:
            return True
    return False


def describe_metadata_status(
    metadata: dict[str, object],
    request: MetadataRepairState | None,
) -> str:
    """Describe the bounded metadata/refresh state exposed to a client.

    Args:
        metadata: Stored ``external_identities.metadata_json`` value.
        request: Current durable request snapshot, or ``None``.

    Returns:
        One of the documented metadata status values.
    """
    if request is not None:
        if request.state == "pending":
            return METADATA_STATUS_REFRESH_PENDING
        if request.state == "running":
            return METADATA_STATUS_REFRESH_RUNNING
        if request.state == "deferred":
            return METADATA_STATUS_REFRESH_DEFERRED
        if request.state == "failed":
            return METADATA_STATUS_REFRESH_FAILED
    if not has_deep_issue_metadata(metadata):
        return METADATA_STATUS_NOT_DEEP_FETCHED
    if has_creator_credits(metadata):
        return METADATA_STATUS_COMPLETE
    return METADATA_STATUS_NO_CREDITS


def refresh_retry_after_seconds(
    request: MetadataRepairState | None,
    *,
    now: datetime,
) -> int | None:
    """Return the bounded retry delay for a deferred or failed request.

    Args:
        request: Current durable request snapshot, or ``None``.
        now: Current timezone-aware UTC timestamp.

    Returns:
        Non-negative whole seconds until another attempt, or ``None``.
    """
    if request is None or request.next_attempt_at is None:
        return None
    if request.state not in ("deferred", "failed"):
        return None
    remaining = (_normalized_timestamp(request.next_attempt_at) - now).total_seconds()
    return max(0, int(remaining))


async def request_issue_metadata_repair(
    db: AsyncSession,
    external_identity_id: int,
    *,
    now: datetime | None = None,
) -> MetadataRepairState:
    """Persist one idempotent durable repair request for a confirmed identity.

    Args:
        db: Async database session owned by the caller.
        external_identity_id: ``external_identities.id`` for the confirmed issue.
        now: Optional clock override used by tests.

    Returns:
        Plain request snapshot, including whether this call created or reopened it.
    """
    current_time = now or datetime.now(UTC)
    request, requested = await refresh_repository.enqueue_request(
        db,
        external_identity_id=external_identity_id,
        now=current_time,
        terminal_reset_before=current_time - COMICVINE_METADATA_MAX_AGE,
    )
    return MetadataRepairState(
        state=request.state,
        attempts=request.attempts,
        next_attempt_at=request.next_attempt_at,
        last_error=request.last_error,
        refresh_requested=requested,
    )


def _comicvine_issue_id(external_id: str) -> int | None:
    """Parse a stored ComicVine issue identity without guessing from other data."""
    normalized = external_id.removeprefix("4000-").strip()
    return int(normalized) if normalized.isdigit() else None


def _backoff_seconds(attempts: int) -> float:
    """Return the bounded retry delay for one attempt count."""
    index = max(0, min(attempts - 1, len(COMICVINE_REPAIR_BACKOFF_SECONDS) - 1))
    return COMICVINE_REPAIR_BACKOFF_SECONDS[index]


def _build_comicvine_client() -> ComicVineClient | None:
    """Build the bounded worker client, or ``None`` when ComicVine is unconfigured."""
    api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
    if not api_key:
        return None
    cache_dir = Path(os.environ.get("COMICVINE_CACHE_DIR", "/tmp/comicpile-comicvine"))
    return ComicVineClient(
        api_key,
        cache_dir,
        timeout_seconds=COMICVINE_REPAIR_REQUEST_TIMEOUT_SECONDS,
        minimum_live_request_interval_seconds=COMICVINE_REPAIR_MIN_REQUEST_INTERVAL_SECONDS,
    )


def _error_code(error: BaseException) -> str:
    """Classify a failure without persisting provider messages or URLs."""
    if isinstance(error, ComicVineRateLimitError):
        return "rate_limit"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ComicVineError):
        return "provider_error"
    return type(error).__name__[:100]


def _retry_delay(error: BaseException, attempts: int) -> float:
    """Combine provider retry-after guidance with bounded local backoff."""
    delay = _backoff_seconds(attempts)
    if isinstance(error, ComicVineRateLimitError):
        provider_delay = error.retry_after_seconds
        if provider_delay is not None and provider_delay > 0:
            delay = max(delay, float(provider_delay))
    return delay


async def _mark_retryable_failure(
    db: AsyncSession,
    *,
    request_id: int,
    attempts: int,
    error: BaseException,
    now: datetime,
    error_code: str | None = None,
) -> str:
    """Persist a bounded retry outcome and return the resulting state."""
    code = error_code or _error_code(error)
    if attempts >= COMICVINE_REPAIR_MAX_ATTEMPTS:
        await refresh_repository.mark_failed(
            db,
            request_id=request_id,
            next_attempt_at=now + timedelta(seconds=COMICVINE_REPAIR_FAILED_COOLDOWN_SECONDS),
            now=now,
            last_error=code,
        )
        await db.commit()
        return "failed"
    await refresh_repository.mark_deferred(
        db,
        request_id=request_id,
        next_attempt_at=now + timedelta(seconds=_retry_delay(error, attempts)),
        now=now,
        last_error=code,
    )
    await db.commit()
    return "deferred"


async def _process_claimed_request(
    db: AsyncSession,
    *,
    request_id: int,
    external_identity_id: int,
    attempts: int,
    client: ComicVineClient | None,
    now: datetime,
) -> str:
    """Process one claimed durable request and persist its terminal state.

    Args:
        db: Async database session.
        request_id: Durable request primary key.
        external_identity_id: ``external_identities.id`` for the confirmed issue.
        attempts: Attempt count after this claim.
        client: Configured provider client, or ``None`` when unconfigured.
        now: Current timezone-aware UTC timestamp.

    Returns:
        One of ``completed``, ``no_credits``, ``deferred``, or ``failed``.
    """
    identity = await db.get(ExternalIdentity, external_identity_id)
    if identity is None:
        await refresh_repository.mark_failed(
            db,
            request_id=request_id,
            next_attempt_at=now + timedelta(seconds=COMICVINE_REPAIR_FAILED_COOLDOWN_SECONDS),
            now=now,
            last_error="identity_missing",
        )
        await db.commit()
        return "failed"
    if identity.provider != "comicvine" or identity.entity_type != "issue":
        await refresh_repository.mark_failed(
            db,
            request_id=request_id,
            next_attempt_at=now + timedelta(seconds=COMICVINE_REPAIR_FAILED_COOLDOWN_SECONDS),
            now=now,
            last_error="identity_ineligible",
        )
        await db.commit()
        return "failed"

    stored_metadata = dict(identity.metadata_json)
    if not metadata_needs_hydration(identity):
        state = (
            "completed" if has_creator_credits(stored_metadata) else "no_credits"
        )
        await refresh_repository.mark_completed(
            db,
            request_id=request_id,
            state=state,
            now=now,
        )
        await db.commit()
        return state

    issue_id = _comicvine_issue_id(identity.external_id)
    if issue_id is None:
        await refresh_repository.mark_failed(
            db,
            request_id=request_id,
            next_attempt_at=now + timedelta(seconds=COMICVINE_REPAIR_FAILED_COOLDOWN_SECONDS),
            now=now,
            last_error="invalid_external_id",
        )
        await db.commit()
        return "failed"

    if client is None:
        await refresh_repository.mark_deferred(
            db,
            request_id=request_id,
            next_attempt_at=now
            + timedelta(seconds=COMICVINE_REPAIR_NOT_CONFIGURED_COOLDOWN_SECONDS),
            now=now,
            last_error="provider_not_configured",
        )
        await db.commit()
        return "deferred"

    try:
        hydrated = await hydrate_issue(db, client, issue_id, refresh=True)
        hydrated_metadata = dict(hydrated.metadata_json)
        await db.commit()
    except ComicVineRateLimitError as error:
        await db.rollback()
        return await _mark_retryable_failure(
            db,
            request_id=request_id,
            attempts=attempts,
            error=error,
            now=now,
            error_code="rate_limit",
        )
    except (ComicVineError, TimeoutError) as error:
        await db.rollback()
        return await _mark_retryable_failure(
            db,
            request_id=request_id,
            attempts=attempts,
            error=error,
            now=now,
        )
    except Exception as error:
        await db.rollback()
        return await _mark_retryable_failure(
            db,
            request_id=request_id,
            attempts=attempts,
            error=error,
            now=now,
        )

    if not has_deep_issue_metadata(hydrated_metadata):
        await refresh_repository.mark_deferred(
            db,
            request_id=request_id,
            next_attempt_at=now + timedelta(seconds=_backoff_seconds(attempts)),
            now=now,
            last_error="deep_metadata_not_persisted",
        )
        await db.commit()
        return "deferred"

    state = "completed" if has_creator_credits(hydrated_metadata) else "no_credits"
    await refresh_repository.mark_completed(
        db,
        request_id=request_id,
        state=state,
        now=now,
    )
    await db.commit()
    return state


async def _drain(
    db: AsyncSession,
    *,
    limit: int,
    now: datetime,
    client: ComicVineClient | None,
) -> MetadataRepairDrainReport:
    """Claim and process due requests using an existing session."""
    claimed = await refresh_repository.claim_due_requests(
        db,
        now=now,
        limit=limit,
        lease_seconds=COMICVINE_REPAIR_LEASE_SECONDS,
    )
    await db.commit()
    if not claimed:
        return MetadataRepairDrainReport(provider_configured=client is not None)

    counts = {"completed": 0, "no_credits": 0, "deferred": 0, "failed": 0}
    for request in claimed:
        try:
            outcome = await _process_claimed_request(
                db,
                request_id=request.request_id,
                external_identity_id=request.external_identity_id,
                attempts=request.attempts,
                client=client,
                now=now,
            )
        except Exception as error:
            # The claim commit already made the request durable. A stalled lease
            # is reclaimable later, so a per-request failure never aborts the
            # rest of the bounded drain or escapes to the cron/request caller.
            logger.warning(
                "comicvine_metadata_repair_job_failed request_id=%s error=%s",
                request.request_id,
                type(error).__name__,
            )
            outcome = "deferred"
        counts[outcome] = counts.get(outcome, 0) + 1
    return MetadataRepairDrainReport(
        claimed=len(claimed),
        completed=counts["completed"],
        no_credits=counts["no_credits"],
        deferred=counts["deferred"],
        failed=counts["failed"],
        provider_configured=client is not None,
    )


async def drain_due_metadata_repairs(
    *,
    limit: int = COMICVINE_REPAIR_DEFAULT_DRAIN_LIMIT,
    now: datetime | None = None,
    db: AsyncSession | None = None,
    client: ComicVineClient | None = None,
    client_factory: object | None = None,
) -> MetadataRepairDrainReport:
    """Run one bounded worker drain of due durable repair requests.

    Args:
        limit: Maximum requests to process, clamped to the documented bound.
        now: Optional clock override used by tests.
        db: Optional caller-owned session; a dedicated session is opened when
            omitted.
        client: Optional preconfigured provider client used by tests.
        client_factory: Optional zero-argument callable returning a provider
            client or ``None``; used by tests.

    Returns:
        Bounded outcome counts for the drain.
    """
    del client_factory  # Reserved for dependency injection in focused tests.
    bounded_limit = max(1, min(limit, COMICVINE_REPAIR_MAX_DRAIN_LIMIT))
    current_time = now or datetime.now(UTC)
    resolved_client = client if client is not None else _build_comicvine_client()
    if db is not None:
        return await _drain(
            db,
            limit=bounded_limit,
            now=current_time,
            client=resolved_client,
        )
    async with AsyncSessionLocal() as owned_db:
        return await _drain(
            owned_db,
            limit=bounded_limit,
            now=current_time,
            client=resolved_client,
        )


def _drop_finished_drain(task: asyncio.Task[None]) -> None:
    """Clear the process-local drain handle and retrieve any exception."""
    global _drain_task
    if _drain_task is task:
        _drain_task = None
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.warning("comicvine_metadata_repair_drain_failed", exc_info=True)


def schedule_metadata_repair_drain() -> bool:
    """Start at most one non-blocking durable drain in this process.

    The durable request row is the source of truth, so a discarded serverless
    task is not data loss: the next read, cron invocation, or lease expiry
    resumes the work.

    Returns:
        True when a new drain task was scheduled, False when one is already
        running or no event loop is available.
    """
    global _drain_task
    if _drain_task is not None and not _drain_task.done():
        return False
    try:
        task = asyncio.create_task(
            drain_due_metadata_repairs(),
            name="comicvine-metadata-repair-drain",
        )
    except RuntimeError:
        logger.warning("comicvine_metadata_repair_schedule_failed reason=no_running_loop")
        return False
    _drain_task = task
    task.add_done_callback(_drop_finished_drain)
    return True
