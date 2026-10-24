"""Best-effort DB-first ComicVine metadata fallback for issue intelligence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
import os
from pathlib import Path

from sqlalchemy import exc as sqlalchemy_exc, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.comicvine_hydration import DEEP_ISSUE_RAW_FIELDS, hydrate_issue
from app.database import AsyncSessionLocal
from app.models.external_identity import ExternalIdentity
from comic_pile.comicvine_provider import (
    ComicVineClient,
    ComicVineError,
    ComicVineRateLimitError,
)

logger = logging.getLogger(__name__)

COMICVINE_METADATA_MAX_AGE = timedelta(days=30)
COMICVINE_REQUEST_TIMEOUT_SECONDS = 5.0
COMICVINE_FALLBACK_MAX_ATTEMPTS = 2
COMICVINE_FALLBACK_RETRY_DELAY_SECONDS = 0.5
COMICVINE_FALLBACK_LOCK_NAMESPACE = 1_065_000_000
# Hydration runs inside the request so Vercel serverless never has to keep a
# detached task alive after the response. This deadline bounds that inline work.
COMICVINE_FALLBACK_INLINE_TIMEOUT_SECONDS = float(
    os.environ.get("COMICVINE_FALLBACK_INLINE_TIMEOUT_SECONDS", "8.0")
)

_pending_metadata_refreshes: dict[int, asyncio.Task[bool]] = {}


def _normalized_timestamp(value: datetime) -> datetime:
    """Normalize a database timestamp to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def metadata_needs_hydration(
    identity: ExternalIdentity,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a confirmed issue identity lacks fresh deep provider metadata.

    Basic ComicVine volume-roster rows are intentionally treated as incomplete because their raw
    payload does not contain the singular issue relationship fields used by the product UI.

    Args:
        identity: Confirmed ComicVine issue identity.
        now: Optional clock override used by tests.

    Returns:
        True when deep metadata is missing or older than the refresh window.
    """
    metadata = identity.metadata_json
    raw_payload = metadata.get("raw_provider_payload")
    if not isinstance(raw_payload, dict):
        return True
    if not DEEP_ISSUE_RAW_FIELDS.issubset(raw_payload):
        return True

    current_time = now or datetime.now(UTC)
    freshness_timestamp = identity.provider_updated_at or identity.updated_at
    updated_at = _normalized_timestamp(freshness_timestamp)
    return current_time - updated_at >= COMICVINE_METADATA_MAX_AGE


def _comicvine_issue_id(external_id: str) -> int | None:
    """Parse a stored ComicVine issue identity without guessing from ComicPile metadata."""
    normalized = external_id.removeprefix("4000-").strip()
    return int(normalized) if normalized.isdigit() else None


async def refresh_issue_metadata(identity_id: int) -> bool:
    """Best-effort inline hydration for one confirmed external identity.

    Runs inside the caller's request so Vercel/serverless platforms never need to keep an
    unbounded detached ``asyncio`` task alive after the response. Cross-process deduplication
    stays in Postgres via ``pg_try_advisory_xact_lock``. Every database connection, advisory-lock,
    and provider failure is caught and logged here, so no exception can escape into an unhandled
    background task.

    Note: interactive read paths must not await this helper. Awaiting it makes the
    user request wait on live ComicVine network I/O (see issue #3248). Reads serve
    trusted stored data immediately and use ``schedule_issue_metadata_refresh``
    so hydration never blocks the response.

    Args:
        identity_id: ``external_identities.id`` for the confirmed ComicVine issue mapping.

    Returns:
        True when fresh metadata was persisted, False when hydration was skipped or failed.
    """
    try:
        async with asyncio.timeout(COMICVINE_FALLBACK_INLINE_TIMEOUT_SECONDS):
            return await _run_issue_hydration(identity_id)
    except TimeoutError:
        logger.warning(
            "comicvine_fallback_inline_timeout identity_id=%s limit_seconds=%.1f",
            identity_id,
            COMICVINE_FALLBACK_INLINE_TIMEOUT_SECONDS,
        )
        return False
    except Exception as exc:
        logger.warning(
            "comicvine_fallback_inline_failed identity_id=%s error=%s",
            identity_id,
            type(exc).__name__,
        )
        return False


async def _hydrate_with_retries(
    db: AsyncSession,
    client: ComicVineClient,
    *,
    identity_id: int,
    issue_id: int,
) -> bool:
    """Run one bounded provider hydration with retry and rate-limit handling."""
    for attempt in range(1, COMICVINE_FALLBACK_MAX_ATTEMPTS + 1):
        try:
            await hydrate_issue(db, client, issue_id, refresh=True)
            await db.commit()
            logger.info(
                "comicvine_fallback_hydrated identity_id=%s comicvine_issue_id=%s attempt=%s",
                identity_id,
                issue_id,
                attempt,
            )
            return True
        except ComicVineRateLimitError:
            logger.warning(
                "comicvine_fallback_deferred identity_id=%s comicvine_issue_id=%s "
                "reason=rate_limit",
                identity_id,
                issue_id,
            )
            return False
        except (ComicVineError, TimeoutError) as exc:
            logger.warning(
                "comicvine_fallback_attempt_failed identity_id=%s comicvine_issue_id=%s "
                "attempt=%s error=%s",
                identity_id,
                issue_id,
                attempt,
                type(exc).__name__,
            )
            if attempt == COMICVINE_FALLBACK_MAX_ATTEMPTS:
                return False
            await asyncio.sleep(COMICVINE_FALLBACK_RETRY_DELAY_SECONDS * attempt)
    return False


async def _run_issue_hydration(identity_id: int) -> bool:
    """Hydrate one confirmed identity under a cross-process advisory lock.

    All database acquisition and advisory-lock failures are handled explicitly so the caller never
    sees a leaked ``Task exception was never retrieved``.

    Args:
        identity_id: ``external_identities.id`` for the confirmed ComicVine issue mapping.

    Returns:
        True when fresh metadata was persisted, False when hydration was skipped or failed.
    """
    api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
    if not api_key:
        logger.info(
            "comicvine_fallback_skipped identity_id=%s reason=missing_api_key",
            identity_id,
        )
        return False

    try:
        async with AsyncSessionLocal() as db:
            lock_key = COMICVINE_FALLBACK_LOCK_NAMESPACE + identity_id
            try:
                lock_result = await db.execute(
                    text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            except (TimeoutError, sqlalchemy_exc.TimeoutError, sqlalchemy_exc.DBAPIError) as exc:
                logger.warning(
                    "comicvine_fallback_lock_unavailable identity_id=%s error=%s",
                    identity_id,
                    type(exc).__name__,
                )
                return False
            if not bool(lock_result.scalar()):
                logger.info(
                    "comicvine_fallback_deduplicated identity_id=%s",
                    identity_id,
                )
                return False

            identity = await db.get(ExternalIdentity, identity_id)
            if (
                identity is None
                or identity.provider != "comicvine"
                or identity.entity_type != "issue"
            ):
                logger.info(
                    "comicvine_fallback_skipped identity_id=%s reason=identity_not_eligible",
                    identity_id,
                )
                return False
            if not metadata_needs_hydration(identity):
                logger.info(
                    "comicvine_fallback_skipped identity_id=%s reason=metadata_fresh",
                    identity_id,
                )
                return False

            issue_id = _comicvine_issue_id(identity.external_id)
            if issue_id is None:
                logger.warning(
                    "comicvine_fallback_skipped identity_id=%s reason=invalid_external_id",
                    identity_id,
                )
                return False

            cache_dir = Path(
                os.environ.get("COMICVINE_CACHE_DIR", "/tmp/comicpile-comicvine")
            )
            client = ComicVineClient(
                api_key,
                cache_dir,
                timeout_seconds=COMICVINE_REQUEST_TIMEOUT_SECONDS,
            )
            return await _hydrate_with_retries(
                db,
                client,
                identity_id=identity_id,
                issue_id=issue_id,
            )
    except (TimeoutError, sqlalchemy_exc.TimeoutError, sqlalchemy_exc.DBAPIError) as exc:
        logger.warning(
            "comicvine_fallback_db_unavailable identity_id=%s error=%s",
            identity_id,
            type(exc).__name__,
        )
        return False


def _drop_finished_refresh(task: asyncio.Task[bool], identity_id: int) -> None:
    """Remove a finished refresh task and swallow its outcome.

    ``refresh_issue_metadata`` already logs and converts every failure to a
    ``False`` return, so this callback only guards against a never-retrieved
    exception warning if the implementation ever raises in the future.
    """
    _pending_metadata_refreshes.pop(identity_id, None)
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.warning(
            "comicvine_fallback_background_failed identity_id=%s",
            identity_id,
            exc_info=True,
        )


def schedule_issue_metadata_refresh(identity_id: int) -> bool:
    """Schedule a non-blocking background metadata refresh for one identity.

    Interactive reads call this instead of awaiting ``refresh_issue_metadata``,
    so user requests serve trusted stored data immediately and never wait on
    live ComicVine network I/O (issue #3248). The refresh runs on its own
    database session; if the platform discards it after the response (for
    example Vercel/serverless freeze), the next stale read simply schedules
    again. At most one refresh per identity is ever in flight in this process;
    cross-process deduplication stays in Postgres via the advisory lock inside
    ``refresh_issue_metadata``.

    Args:
        identity_id: ``external_identities.id`` for the confirmed ComicVine issue mapping.

    Returns:
        True when a new background refresh was scheduled, False when one is
        already pending or no running event loop could accept the task.
    """
    pending = _pending_metadata_refreshes.get(identity_id)
    if pending is not None and not pending.done():
        return False
    try:
        task = asyncio.create_task(
            refresh_issue_metadata(identity_id),
            name=f"comicvine-metadata-refresh-{identity_id}",
        )
    except RuntimeError:
        logger.warning(
            "comicvine_fallback_schedule_failed identity_id=%s reason=no_running_loop",
            identity_id,
        )
        return False
    _pending_metadata_refreshes[identity_id] = task
    task.add_done_callback(lambda finished: _drop_finished_refresh(finished, identity_id))
    return True
