"""Deterministic ComicVine issue resolution from a confirmed thread-series mapping."""

from __future__ import annotations

import asyncio
import logging
import os
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.comicvine_hydration import hydrate_issue
from app.database import AsyncSessionLocal
from app.external_identities import (
    ExternalIdentityMappingError,
    link_issue_external_identity,
    upsert_external_identity,
)
from app.models import Issue
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from comic_pile.comicvine_provider import (
    ComicVineClient,
    ComicVineError,
    ComicVineRateLimitError,
)

COMICVINE_PROVIDER = "comicvine"
COMICVINE_SERIES_RESOLUTION_LOCK_NAMESPACE = 1_065_100_000
COMICVINE_COLLECTION_PAGE_LIMIT = 100

_pending_resolutions: dict[int, asyncio.Task[None]] = {}

logger = logging.getLogger(__name__)


def _normalize_issue_label(value: str | None) -> str:
    """Strip a leading hash, NFKC-normalize, and lowercase an issue label."""
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = normalized.removeprefix("#").strip()
    return " ".join(normalized.split()).lower()


def _is_ambiguous_special(label: str) -> bool:
    """Return True for labels that likely belong to a separate ComicVine volume."""
    normalized = _normalize_issue_label(label)
    if not normalized:
        return False
    if normalized.isdigit():
        return False
    for keyword in ("annual", "special", "one-shot", "giant"):
        if normalized.startswith(keyword) or f" {keyword} " in f" {normalized} ":
            return True
    return False


async def _confirmed_series_identity(
    db: AsyncSession, thread_id: int
) -> ExternalIdentity | None:
    result = await db.execute(
        select(ExternalIdentity)
        .join(
            ThreadExternalSeriesMapping,
            ThreadExternalSeriesMapping.external_identity_id == ExternalIdentity.id,
        )
        .where(
            ThreadExternalSeriesMapping.thread_id == thread_id,
            ThreadExternalSeriesMapping.status == "confirmed",
            ExternalIdentity.provider == COMICVINE_PROVIDER,
            ExternalIdentity.entity_type == "series",
        )
        .order_by(
            ThreadExternalSeriesMapping.confidence.desc().nullslast(),
            ExternalIdentity.id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _find_existing_mapping(
    db: AsyncSession, issue_id: int
) -> IssueExternalIdentityMapping | None:
    result = await db.execute(
        select(IssueExternalIdentityMapping)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(
            IssueExternalIdentityMapping.issue_id == issue_id,
            ExternalIdentity.provider == COMICVINE_PROVIDER,
        )
        .order_by(IssueExternalIdentityMapping.id)
    )
    return result.scalar_one_or_none()


def _build_identity_from_volume_row(
    row: dict[str, object], *, volume_id: int, volume_name: str | None
) -> ExternalIdentity:
    external_id = str(row["id"])
    url = str(row.get("site_detail_url") or "")
    issue_number = str(row.get("issue_number") or "")
    name = str(row.get("name") or "")
    raw = datetime.now(UTC)
    return ExternalIdentity(
        provider=COMICVINE_PROVIDER,
        entity_type="issue",
        external_id=external_id,
        external_url=url or None,
        metadata_json={
            "issue_number": issue_number,
            "name": name,
            "volume": {"id": volume_id, "name": volume_name},
            "volume_id": volume_id,
            "volume_name": volume_name,
            "source": "series_resolution_volume_roster",
        },
        provider_updated_at=raw,
    )


async def _resolve_issue_from_series(
    db: AsyncSession,
    client: ComicVineClient,
    series_identity: ExternalIdentity,
    issue_label: str | None,
) -> list[ExternalIdentity]:
    series_metadata = series_identity.metadata_json
    volume_ref = series_metadata.get("volume")
    volume_id: int | None = None
    volume_name: str | None = None
    if isinstance(volume_ref, dict):
        volume_id = _volume_id(volume_ref)
        volume_name = _string(volume_ref.get("name"))
    if volume_id is None:
        volume_id = _integer(series_metadata.get("volume_id"))
    if volume_name is None:
        volume_name = _string(series_metadata.get("volume_name"))
    if volume_id is None:
        return []

    normalized_label = _normalize_issue_label(issue_label)
    if not normalized_label or normalized_label.isdigit() is False:
        return []

    provider_rows: list[dict[str, object]] = []
    offset = 0
    while True:
        response = await client.request(
            "issues",
            "issues",
            {
                "filter": f"volume:{volume_id}",
                "limit": COMICVINE_COLLECTION_PAGE_LIMIT,
                "offset": offset,
            },
        )
        results = response.payload.get("results")
        if not isinstance(results, list):
            return []
        page_rows = [row for row in results if isinstance(row, dict)]
        for row in page_rows:
            vol = row.get("volume")
            if isinstance(vol, dict) and vol.get("id") not in (None, volume_id):
                return []
        provider_rows.extend(page_rows)
        if len(page_rows) < COMICVINE_COLLECTION_PAGE_LIMIT:
            break
        total = response.payload.get("number_of_total_results")
        if isinstance(total, int) and len(provider_rows) >= total:
            break
        offset += len(page_rows)

    matched_rows: list[dict[str, object]] = []
    for row in provider_rows:
        row_label = _normalize_issue_label(str(row.get("issue_number") or ""))
        if row_label and row_label == normalized_label:
            matched_rows.append(row)

    seen: set[str] = set()
    unique_rows: list[dict[str, object]] = []
    for row in matched_rows:
        eid = str(row.get("id") or "")
        if eid and eid not in seen:
            seen.add(eid)
            unique_rows.append(row)

    return [
        _build_identity_from_volume_row(row, volume_id=volume_id, volume_name=volume_name)
        for row in unique_rows
    ]


async def _run_series_resolution(issue_id: int, user_id: int) -> None:
    api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
    if not api_key:
        logger.info(
            "comicvine_series_resolution_skipped issue_id=%s reason=missing_api_key",
            issue_id,
        )
        return

    cache_dir = Path(
        os.environ.get("COMICVINE_CACHE_DIR", "/tmp/comicpile-comicvine")
    )
    client = ComicVineClient(
        api_key,
        cache_dir,
        timeout_seconds=5.0,
    )

    async with AsyncSessionLocal() as db:
        lock_key = COMICVINE_SERIES_RESOLUTION_LOCK_NAMESPACE + issue_id
        lock_result = await db.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        if not bool(lock_result.scalar()):
            logger.info(
                "comicvine_series_resolution_deduplicated issue_id=%s",
                issue_id,
            )
            return

        issue = await db.get(Issue, issue_id)
        if issue is None:
            return

        existing = await _find_existing_mapping(db, issue_id)
        if existing is not None and existing.status == "confirmed":
            logger.info(
                "comicvine_series_resolution_skipped issue_id=%s reason=already_confirmed",
                issue_id,
            )
            return

        series_identity = await _confirmed_series_identity(db, issue.thread_id)
        if series_identity is None:
            return

        if _is_ambiguous_special(issue.issue_number):
            logger.info(
                "comicvine_series_resolution_skipped issue_id=%s reason=ambiguous_special",
                issue_id,
            )
            return

        try:
            identities = await _resolve_issue_from_series(
                db, client, series_identity, issue.issue_number
            )
        except ComicVineRateLimitError:
            logger.warning(
                "comicvine_series_resolution_deferred issue_id=%s reason=rate_limit",
                issue_id,
            )
            return
        except (ComicVineError, TimeoutError) as exc:
            logger.warning(
                "comicvine_series_resolution_failed issue_id=%s error=%s",
                issue_id,
                type(exc).__name__,
            )
            return

        if not identities:
            return

        identity = identities[0]
        try:
            async with db.begin_nested():
                persisted = await upsert_external_identity(
                    db,
                    provider=COMICVINE_PROVIDER,
                    entity_type="issue",
                    external_id=identity.external_id,
                    external_url=identity.external_url,
                    metadata_json=identity.metadata_json,
                    provider_updated_at=identity.provider_updated_at,
                )
        except IntegrityError:
            persisted = await db.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.provider == COMICVINE_PROVIDER,
                    ExternalIdentity.entity_type == "issue",
                    ExternalIdentity.external_id == identity.external_id,
                )
            )
            if persisted is None:
                return

        confidence = 1.0 if len(identities) == 1 else 0.55
        try:
            mapping = await link_issue_external_identity(
                db,
                user_id=user_id,
                issue_id=issue_id,
                external_identity_id=persisted.id,
                status="confirmed",
                evidence_source="series_volume_resolution",
                confidence=confidence,
            )
        except ExternalIdentityMappingError as exc:
            logger.warning(
                "comicvine_series_resolution_mapping_failed issue_id=%s error=%s",
                issue_id,
                exc,
            )
            return

        try:
            await db.commit()
        except Exception:
            logger.warning(
                "comicvine_series_resolution_commit_failed issue_id=%s",
                issue_id,
                exc_info=True,
            )
            return

        mapping_id = mapping.id
        comicvine_issue_id = _comicvine_issue_id(persisted.external_id)
        if comicvine_issue_id is not None:
            try:
                await hydrate_issue(db, client, comicvine_issue_id, refresh=True)
                await db.commit()
            except (ComicVineError, TimeoutError) as exc:
                logger.info(
                    "comicvine_series_resolution_hydration_deferred "
                    "issue_id=%s mapping_id=%s error=%s",
                    issue_id,
                    mapping_id,
                    type(exc).__name__,
                )
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "comicvine_series_resolution_hydration_failed "
                    "issue_id=%s mapping_id=%s error=%s",
                    issue_id,
                    mapping_id,
                    type(exc).__name__,
                )

        logger.info(
            "comicvine_series_resolution_completed issue_id=%s external_id=%s "
            "confidence=%s provider_count=%s",
            issue_id,
            persisted.external_id,
            confidence,
            len(identities),
        )


def schedule_series_issue_resolution(
    db: AsyncSession, issue_id: int, user_id: int
) -> bool:
    """Schedule at most one background resolution for an unmapped issue.

    The resolution runs asynchronously and does not block the caller.  In-process
    deduplication prevents fan-out from parallel requests for the same issue; a
    PostgreSQL advisory transaction lock provides cross-process safety.

    Args:
        db: Async database session (used for fast pre-check only).
        issue_id: ComicPile issue identifier.
        user_id: Owner user ID for authorization.

    Returns:
        True when a new background task was scheduled, False when one is already
        pending or the issue is already confirmed.
    """
    pending = _pending_resolutions.get(issue_id)
    if pending is not None and not pending.done():
        return False

    task = asyncio.create_task(
        _run_series_resolution(issue_id, user_id),
        name=f"comicvine-series-resolution-{issue_id}",
    )
    _pending_resolutions[issue_id] = task
    task.add_done_callback(lambda finished: _pending_resolutions.pop(issue_id, None))
    return True


def _string(value: object) -> str | None:
    return str(value) if isinstance(value, (str, int)) and str(value).strip() else None


def _integer(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _volume_id(metadata: dict[str, object] | None) -> int | None:
    if not isinstance(metadata, dict):
        return None
    volume = metadata.get("volume")
    if isinstance(volume, dict):
        result = _integer(volume.get("id"))
        if result is not None:
            return result
    return _integer(metadata.get("volume_id"))


def _comicvine_issue_id(external_id: str) -> int | None:
    normalized = external_id.removeprefix("4000-").strip()
    return int(normalized) if normalized.isdigit() else None
