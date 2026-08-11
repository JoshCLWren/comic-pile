"""Best-effort DB-first ComicVine metadata fallback for issue intelligence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
import os
from pathlib import Path

from sqlalchemy import text

from app.comicvine_hydration import hydrate_issue
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

_REQUIRED_DEEP_RAW_FIELDS = frozenset(
    {
        "id",
        "name",
        "issue_number",
        "cover_date",
        "store_date",
        "image",
        "volume",
        "person_credits",
        "character_credits",
        "team_credits",
        "story_arc_credits",
        "date_last_updated",
    }
)

_pending_hydrations: dict[int, asyncio.Task[None]] = {}


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
    if not _REQUIRED_DEEP_RAW_FIELDS.issubset(raw_payload):
        return True

    current_time = now or datetime.now(UTC)
    updated_at = _normalized_timestamp(identity.updated_at)
    return current_time - updated_at >= COMICVINE_METADATA_MAX_AGE


def _comicvine_issue_id(external_id: str) -> int | None:
    """Parse a stored ComicVine issue identity without guessing from ComicPile metadata."""
    normalized = external_id.removeprefix("4000-").strip()
    return int(normalized) if normalized.isdigit() else None


def _clear_pending(identity_id: int, task: asyncio.Task[None]) -> None:
    """Remove a completed task only when it is still the registered hydration."""
    if _pending_hydrations.get(identity_id) is task:
        _pending_hydrations.pop(identity_id, None)


def schedule_issue_metadata_hydration(identity_id: int) -> bool:
    """Schedule at most one in-process hydration for one confirmed external identity.

    Cross-process/provider deduplication is enforced again inside the database task with a
    PostgreSQL advisory transaction lock, so concurrent serverless instances cannot fan out the
    same provider lookup.

    Args:
        identity_id: ``external_identities.id`` for the confirmed ComicVine issue mapping.

    Returns:
        True when a new task was scheduled, False when one is already pending.
    """
    pending = _pending_hydrations.get(identity_id)
    if pending is not None and not pending.done():
        return False

    task = asyncio.create_task(
        _run_issue_hydration(identity_id),
        name=f"comicvine-fallback-{identity_id}",
    )
    _pending_hydrations[identity_id] = task
    task.add_done_callback(lambda finished: _clear_pending(identity_id, finished))
    return True


async def _run_issue_hydration(identity_id: int) -> None:
    """Hydrate one confirmed identity under a cross-process advisory lock."""
    api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
    if not api_key:
        logger.info(
            "comicvine_fallback_skipped identity_id=%s reason=missing_api_key",
            identity_id,
        )
        return

    async with AsyncSessionLocal() as db:
        lock_key = COMICVINE_FALLBACK_LOCK_NAMESPACE + identity_id
        lock_result = await db.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        if not bool(lock_result.scalar()):
            logger.info(
                "comicvine_fallback_deduplicated identity_id=%s",
                identity_id,
            )
            return

        identity = await db.get(ExternalIdentity, identity_id)
        if identity is None or identity.provider != "comicvine" or identity.entity_type != "issue":
            logger.info(
                "comicvine_fallback_skipped identity_id=%s reason=identity_not_eligible",
                identity_id,
            )
            return
        if not metadata_needs_hydration(identity):
            logger.info(
                "comicvine_fallback_skipped identity_id=%s reason=metadata_fresh",
                identity_id,
            )
            return

        issue_id = _comicvine_issue_id(identity.external_id)
        if issue_id is None:
            logger.warning(
                "comicvine_fallback_skipped identity_id=%s reason=invalid_external_id",
                identity_id,
            )
            return

        cache_dir = Path(
            os.environ.get("COMICVINE_CACHE_DIR", "/tmp/comicpile-comicvine")
        )
        client = ComicVineClient(
            api_key,
            cache_dir,
            timeout_seconds=COMICVINE_REQUEST_TIMEOUT_SECONDS,
        )

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
                return
            except ComicVineRateLimitError:
                logger.warning(
                    "comicvine_fallback_deferred identity_id=%s comicvine_issue_id=%s "
                    "reason=rate_limit",
                    identity_id,
                    issue_id,
                )
                return
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
                    return
                await asyncio.sleep(COMICVINE_FALLBACK_RETRY_DELAY_SECONDS * attempt)
