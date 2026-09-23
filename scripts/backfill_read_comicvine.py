#!/usr/bin/env python3
"""Backfill ComicVine creator metadata for read ComicPile issues.

This operator command is intentionally isolated from ``app.database`` and the
Pydantic settings stack. It reads the already-exported ``DATABASE_URL`` from
the process environment (for example, from direnv), creates its own SQLAlchemy
engine, and never falls back to a local or test database.

The command is idempotent and resumable. It exhausts configured local ComicVine
SQLite identity and creator evidence before constructing a live provider request,
then reloads inventory between four stages:

1. persist identities proven from local evidence;
2. hydrate stored/local creator payloads;
3. resolve only provider-dependent identities; and
4. hydrate creator metadata for newly mapped issues.

ComicVine's persistent response cache, request ledger, paced live starts, and
per-resource cooldown state are reused. A throttle on one resource defers only
work requiring that resource, so unrelated cached or satisfiable work continues.
The inventory query deliberately selects only metadata-state flags and series
identifiers, not every large provider JSON blob in the read library.

Examples:
    uv run python scripts/backfill_read_comicvine.py --user-id 1 --dry-run
    uv run python scripts/backfill_read_comicvine.py --user-id 1 --limit 25
    uv run python scripts/backfill_read_comicvine.py --user-id 1
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
import importlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_comicvine_provider = importlib.import_module("comic_pile.comicvine_provider")
ComicVineClient = _comicvine_provider.ComicVineClient
ComicVineError = _comicvine_provider.ComicVineError
ComicVineRateLimitError = _comicvine_provider.ComicVineRateLimitError

from comic_pile.comicvine_identity_repair import normalize_title
from comic_pile.local_comicvine import (
    LOCAL_COMICVINE_DB_ENV,
    LocalComicVineSnapshot,
)

DEFAULT_REPORT = Path("/tmp/comicpile-read-comicvine-backfill.json")
LOCAL_DB_ENV = "COMICVINE_LOCAL_DB"
OPERATOR_MINIMUM_LIVE_REQUEST_INTERVAL_SECONDS = 1.5
OPERATOR_FALLBACK_COOLDOWN_SECONDS = 60.0
OPERATOR_MAX_FALLBACK_COOLDOWN_SECONDS = 3600.0
_YEAR_RANGE_RE = re.compile(r"\s*\((?P<start>\d{4})\s*-\s*(?:\d{4}|present)\)\s*$", re.IGNORECASE)
_YEAR_SUFFIX_RE = re.compile(r"\s*\((?P<year>\d{4})\)\s*$")


@dataclass(frozen=True)
class ReadIssue:
    """One read issue plus the bounded ComicVine evidence needed by the operator."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    position: int
    identity_id: int | None
    external_id: str | None
    has_creator_credits: bool
    has_person_credit_source: bool
    creator_credit_count: int
    series_identity_id: int | None
    series_external_id: str | None
    series_volume_id: int | None
    series_name: str | None
    sibling_volume_ids: tuple[int, ...] = ()


@dataclass
class BackfillResult:
    """Machine-readable outcome for one attempted read-issue backfill."""

    issue_id: int
    thread_id: int
    title: str
    issue_number: str
    status: str
    comicvine_issue_id: str | None = None
    creator_credits: int = 0
    detail: str | None = None
    phase: str = "creator"
    provenance: str | None = None
    resource: str | None = None


@dataclass(frozen=True)
class IdentityCandidate:
    """One identity proven by local or provider evidence."""

    identity_id: int | None
    external_id: str
    volume_id: int
    volume_name: str | None
    source: str


def _async_url(raw: str) -> str:
    """Normalize a Neon/libpq URL into a SQLAlchemy asyncpg URL."""
    url = raw.strip()
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    elif url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.pop("channel_binding", None)
    sslmode = query.pop("sslmode", None)
    if sslmode in {"require", "verify-full", "verify-ca"} or "ssl" not in query:
        query["ssl"] = "require"
    return urlunparse(parsed._replace(query=urlencode(query)))


def _require_database_url(explicit: str | None) -> str:
    """Return only an explicitly supplied/process-exported database URL."""
    value = explicit if explicit is not None else os.environ.get("DATABASE_URL")
    if value is None or not value.strip():
        raise SystemExit(
            "DATABASE_URL is required. This script never falls back to app config, "
            "TEST_DATABASE_URL, or a local database."
        )
    return value.strip()


def _database_target(database_url: str) -> tuple[str, str]:
    """Return safe host/database display values without credentials."""
    parsed = urlparse(database_url)
    return parsed.hostname or "<unknown>", parsed.path.lstrip("/") or "<unknown>"


def _normalize_issue_label(value: str | None) -> str:
    """Normalize issue labels exactly like the deterministic app resolver."""
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = normalized.removeprefix("#").strip()
    return " ".join(normalized.split()).lower()


def _is_ambiguous_special(label: str | None) -> bool:
    """Return true for labels that likely belong to a separate provider volume."""
    normalized = _normalize_issue_label(label)
    if not normalized or normalized.isdigit():
        return False
    for keyword in ("annual", "special", "one-shot", "giant"):
        if normalized.startswith(keyword) or f" {keyword} " in f" {normalized} ":
            return True
    return False


def _title_search_hint(title: str) -> tuple[str, int | None]:
    """Return a normalized title and an optional explicit start year for provider search."""
    remaining = title.strip()
    year_match = _YEAR_RANGE_RE.search(remaining)
    if year_match is None:
        year_match = _YEAR_SUFFIX_RE.search(remaining)
    if year_match is None:
        return remaining, None
    return remaining[: year_match.start()].rstrip(), int(year_match.group("start" if "start" in year_match.groupdict() else "year"))


def _integer(value: object) -> int | None:
    """Coerce a numeric provider value without accepting booleans."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _volume_ids(value: object) -> tuple[int, ...]:
    """Normalize a PostgreSQL or test-provided volume ID collection."""
    if value is None:
        return ()
    raw_values = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    ids = {
        volume_id
        for item in raw_values
        if (volume_id := _integer(str(item).strip())) is not None
    }
    return tuple(sorted(ids))


def _string(value: object) -> str | None:
    """Coerce a non-empty string/int provider value to text."""
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        normalized = str(value).strip()
        return normalized or None
    return None


def _series_volume_id(volume_id: object, external_id: str | None) -> int | None:
    """Resolve a ComicVine volume ID from metadata first, stable identity second."""
    found = _integer(volume_id)
    if found is not None:
        return found
    if external_id:
        return _integer(external_id.removeprefix("4050-").strip())
    return None


def _local_snapshot_from_environment() -> LocalComicVineSnapshot:
    """Build the optional read-only local ComicVine snapshot from explicit environment names."""
    configured = os.environ.get(LOCAL_DB_ENV) or os.environ.get(LOCAL_COMICVINE_DB_ENV)
    return LocalComicVineSnapshot(configured)


def _local_alias_values(value: object) -> list[str]:
    """Return individual local volume aliases without treating a field as title proof."""
    if not isinstance(value, str) or not value.strip():
        return []
    raw = value.strip()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list):
        return [str(item).strip() for item in decoded if str(item).strip()]
    if isinstance(decoded, dict):
        return [str(item).strip() for item in decoded.values() if str(item).strip()]
    return [part.strip() for part in raw.replace("|", "\n").splitlines() if part.strip()]


def _local_volume_title_matches(data: Mapping[str, object], title: str) -> bool:
    """Return whether a local volume name or alias exactly matches a normalized title."""
    expected = normalize_title(title)
    values: list[str] = []
    name = data.get("name")
    if isinstance(name, str) and name.strip():
        values.append(name)
    values.extend(_local_alias_values(data.get("aliases")))
    return any(normalize_title(value) == expected for value in values)


def _local_issue_matches(
    rows: list[dict[str, object]],
    issue_number: str,
) -> dict[int, dict[str, object]]:
    """Return unique exact-label issue rows keyed by provider ID."""
    expected = _normalize_issue_label(issue_number)
    if not expected:
        return {}
    matches: dict[int, dict[str, object]] = {}
    for row in rows:
        labels = {
            _normalize_issue_label(_string(row.get("issue_number"))),
            _normalize_issue_label(_string(row.get("name"))),
        }
        if expected not in labels:
            continue
        provider_id = _integer(row.get("id"))
        if provider_id is not None:
            matches.setdefault(provider_id, row)
    return matches


async def _local_roster(
    snapshot: LocalComicVineSnapshot,
    volume_id: int,
    cache: dict[int, list[dict[str, object]]],
) -> list[dict[str, object]]:
    """Read one local volume roster once without blocking the event loop."""
    if volume_id not in cache:
        rows = await asyncio.to_thread(snapshot.get_volume_issues, volume_id)
        cache[volume_id] = [dict(row.data) for row in rows]
    return cache[volume_id]


async def _find_local_identity_candidate(
    snapshot: LocalComicVineSnapshot,
    issue: ReadIssue,
    roster_cache: dict[int, list[dict[str, object]]],
) -> tuple[int, dict[str, object]] | None:
    """Find one issue identity proven by complete local volume evidence."""
    if not snapshot.available:
        return None

    volume_ids = {
        volume_id
        for volume_id in (issue.series_volume_id, *issue.sibling_volume_ids)
        if volume_id is not None
    }
    if not volume_ids:
        hits = await asyncio.to_thread(snapshot.search_volumes, issue.thread_title, limit=250)
        exact_hits = [
            dict(hit.data)
            for hit in hits
            if _local_volume_title_matches(hit.data, issue.thread_title)
            and _integer(hit.data.get("id")) is not None
        ]
        volume_ids = {
            volume_id
            for hit in exact_hits
            if (volume_id := _integer(hit.data.get("id"))) is not None
        }
        if not volume_ids:
            return None

    rosters: dict[int, list[dict[str, object]]] = {}
    for volume_id in sorted(volume_ids):
        roster = await _local_roster(snapshot, volume_id, roster_cache)
        if not roster:
            return None
        rosters[volume_id] = roster

    matches: dict[int, tuple[int, dict[str, object]]] = {}
    for volume_id, roster in rosters.items():
        for provider_id, row in _local_issue_matches(roster, issue.issue_number).items():
            matches.setdefault(provider_id, (volume_id, row))
    if len(matches) != 1:
        return None
    return next(iter(matches.values()))


async def _local_creator_payload(
    snapshot: LocalComicVineSnapshot,
    external_id: str,
) -> dict[str, object] | None:
    """Return a provider-shaped local issue only when it has creator credits."""
    provider_id = _integer(external_id.removeprefix("4000-"))
    if provider_id is None:
        return None
    local = await asyncio.to_thread(snapshot.get_issue, provider_id)
    if local is None:
        return None
    credits = local.data.get("person_credits")
    if not isinstance(credits, list) or not credits:
        return None
    payload = dict(local.data)
    payload["id"] = provider_id
    volume_id = _integer(payload.get("volume_id"))
    if volume_id is not None:
        payload["volume"] = {"id": volume_id}
    return payload


def _compact_reference(value: object) -> dict[str, object] | None:
    """Keep only stable fields from a ComicVine relationship object."""
    if not isinstance(value, dict):
        return None
    allowed = ("id", "name", "api_detail_url", "site_detail_url")
    compact = {key: value[key] for key in allowed if key in value}
    if "role" in value:
        compact["role"] = value["role"]
    return compact


def _compact_references(value: object) -> list[dict[str, object]]:
    """Normalize a ComicVine relationship array."""
    if not isinstance(value, list):
        return []
    return [
        compact
        for item in value
        if (compact := _compact_reference(item)) is not None
    ]


def _provider_timestamp(value: object) -> datetime | None:
    """Parse an optional ComicVine update timestamp."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_issue_metadata(result: dict[str, object]) -> dict[str, object]:
    """Normalize the singular issue payload into ComicPile's creator-aware shape."""
    image = result.get("image") if isinstance(result.get("image"), dict) else None
    primary_image: str | None = None
    if isinstance(image, dict):
        for key in ("original_url", "super_url", "medium_url", "small_url"):
            candidate = image.get(key)
            if isinstance(candidate, str) and candidate:
                primary_image = candidate
                break

    return {
        "name": result.get("name"),
        "issue_number": result.get("issue_number"),
        "cover_date": result.get("cover_date"),
        "store_date": result.get("store_date"),
        "volume": _compact_reference(result.get("volume")),
        "primary_image": primary_image,
        "creator_credits": _compact_references(result.get("person_credits")),
        "characters": _compact_references(result.get("character_credits")),
        "teams": _compact_references(result.get("team_credits")),
        "story_arcs": _compact_references(result.get("story_arc_credits")),
        "raw_provider_payload": result,
    }


def _creator_credit_count(metadata: dict[str, object]) -> int:
    """Count analytics-addressable normalized creator credits."""
    credits = metadata.get("creator_credits")
    if not isinstance(credits, list):
        return 0
    return sum(
        1
        for credit in credits
        if isinstance(credit, dict)
        and _integer(credit.get("id")) is not None
        and isinstance(credit.get("name"), str)
        and bool(str(credit["name"]).strip())
    )


def _parser() -> argparse.ArgumentParser:
    """Build the operator CLI parser."""
    parser = argparse.ArgumentParser(
        description="Backfill ComicVine creator metadata for read ComicPile issues."
    )
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL. If omitted, the already-exported DATABASE_URL is required.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inventory current mappings/metadata without calling ComicVine or writing rows.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force singular ComicVine issue refresh even when creator_credits already exist.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser


def _engine(database_url: str) -> AsyncEngine:
    """Create one small explicit-URL engine for the operator process."""
    return create_async_engine(
        _async_url(database_url),
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )


async def _load_read_issues(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int | None,
) -> list[ReadIssue]:
    """Load read issues with only bounded creator-state and series evidence."""
    sql = """
        SELECT
            i.id AS issue_id,
            i.thread_id,
            t.title AS thread_title,
            i.issue_number,
            i.position,
            issue_cv.identity_id,
            issue_cv.external_id,
            COALESCE(issue_cv.has_creator_credits, FALSE) AS has_creator_credits,
            COALESCE(issue_cv.has_person_credit_source, FALSE) AS has_person_credit_source,
            COALESCE(issue_cv.creator_credit_count, 0) AS creator_credit_count,
            series_cv.identity_id AS series_identity_id,
            series_cv.external_id AS series_external_id,
            series_cv.volume_id_text,
            series_cv.series_name,
            sibling_cv.sibling_volume_ids
        FROM issues i
        JOIN threads t ON t.id = i.thread_id
        LEFT JOIN LATERAL (
            SELECT
                ei.id AS identity_id,
                ei.external_id,
                jsonb_typeof(ei.metadata_json::jsonb -> 'creator_credits') = 'array'
                    AS has_creator_credits,
                (
                    jsonb_typeof(ei.metadata_json::jsonb -> 'person_credits') = 'array'
                    OR jsonb_typeof(
                        ei.metadata_json::jsonb -> 'raw_provider_payload' -> 'person_credits'
                    ) = 'array'
                ) AS has_person_credit_source,
                CASE
                    WHEN jsonb_typeof(ei.metadata_json::jsonb -> 'creator_credits') = 'array'
                    THEN jsonb_array_length(ei.metadata_json::jsonb -> 'creator_credits')
                    WHEN jsonb_typeof(
                        ei.metadata_json::jsonb -> 'raw_provider_payload' -> 'person_credits'
                    ) = 'array'
                    THEN jsonb_array_length(
                        ei.metadata_json::jsonb -> 'raw_provider_payload' -> 'person_credits'
                    )
                    WHEN jsonb_typeof(ei.metadata_json::jsonb -> 'person_credits') = 'array'
                    THEN jsonb_array_length(ei.metadata_json::jsonb -> 'person_credits')
                    ELSE 0
                END AS creator_credit_count
            FROM issue_external_identity_mappings iem
            JOIN external_identities ei
              ON ei.id = iem.external_identity_id
            WHERE iem.issue_id = i.id
              AND iem.status = 'confirmed'
              AND ei.provider = 'comicvine'
              AND ei.entity_type = 'issue'
            ORDER BY iem.confidence DESC NULLS LAST, ei.id
            LIMIT 1
        ) issue_cv ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                ei.id AS identity_id,
                ei.external_id,
                COALESCE(
                    ei.metadata_json::jsonb -> 'volume' ->> 'id',
                    ei.metadata_json::jsonb ->> 'volume_id'
                ) AS volume_id_text,
                COALESCE(
                    ei.metadata_json::jsonb ->> 'volume_name',
                    ei.metadata_json::jsonb ->> 'name'
                ) AS series_name
            FROM thread_external_series_mappings tsm
            JOIN external_identities ei
              ON ei.id = tsm.external_identity_id
            WHERE tsm.thread_id = t.id
              AND tsm.status = 'confirmed'
              AND ei.provider = 'comicvine'
              AND ei.entity_type = 'series'
            ORDER BY tsm.confidence DESC NULLS LAST, ei.id
            LIMIT 1
        ) series_cv ON TRUE
        LEFT JOIN LATERAL (
            SELECT ARRAY_AGG(DISTINCT COALESCE(
                ei.metadata_json::jsonb -> 'volume' ->> 'id',
                ei.metadata_json::jsonb ->> 'volume_id',
                ei.metadata_json::jsonb -> 'raw_provider_payload' -> 'volume' ->> 'id'
            )) AS sibling_volume_ids
            FROM issues sibling_issue
            JOIN issue_external_identity_mappings sibling_iem
              ON sibling_iem.issue_id = sibling_issue.id
             AND sibling_iem.status = 'confirmed'
            JOIN external_identities sibling_ei
              ON sibling_ei.id = sibling_iem.external_identity_id
             AND sibling_ei.provider = 'comicvine'
             AND sibling_ei.entity_type = 'issue'
            WHERE sibling_issue.thread_id = i.thread_id
              AND sibling_issue.id <> i.id
              AND COALESCE(
                  sibling_ei.metadata_json::jsonb -> 'volume' ->> 'id',
                  sibling_ei.metadata_json::jsonb ->> 'volume_id',
                  sibling_ei.metadata_json::jsonb -> 'raw_provider_payload' -> 'volume' ->> 'id'
              ) IS NOT NULL
        ) sibling_cv ON TRUE
        WHERE t.user_id = :user_id
          AND t.is_test IS FALSE
          AND i.status = 'read'
        ORDER BY t.queue_position, t.id, i.position, i.id
    """
    params: dict[str, object] = {"user_id": user_id}
    if limit is not None:
        sql += "\nLIMIT :limit"
        params["limit"] = limit

    rows = (await db.execute(text(sql), params)).mappings().all()
    return [
        ReadIssue(
            issue_id=int(row["issue_id"]),
            thread_id=int(row["thread_id"]),
            thread_title=str(row["thread_title"]),
            issue_number=str(row["issue_number"]),
            position=int(row["position"]),
            identity_id=int(row["identity_id"]) if row["identity_id"] is not None else None,
            external_id=str(row["external_id"]) if row["external_id"] is not None else None,
            has_creator_credits=bool(row["has_creator_credits"]),
            has_person_credit_source=bool(row["has_person_credit_source"]),
            creator_credit_count=int(row["creator_credit_count"]),
            series_identity_id=(
                int(row["series_identity_id"])
                if row["series_identity_id"] is not None
                else None
            ),
            series_external_id=(
                str(row["series_external_id"])
                if row["series_external_id"] is not None
                else None
            ),
            series_volume_id=_series_volume_id(
                row["volume_id_text"],
                str(row["series_external_id"])
                if row["series_external_id"] is not None
                else None,
            ),
            series_name=str(row["series_name"]) if row["series_name"] is not None else None,
            sibling_volume_ids=_volume_ids(row["sibling_volume_ids"]),
        )
        for row in rows
    ]


async def _user_exists(db: AsyncSession, user_id: int) -> bool:
    """Return whether the target user exists on the selected database."""
    value = await db.scalar(
        text("SELECT EXISTS(SELECT 1 FROM users WHERE id = :user_id)"),
        {"user_id": user_id},
    )
    return bool(value)


async def _normalize_existing_creator_credits(
    db: AsyncSession,
    *,
    identity_id: int,
) -> int | None:
    """Merge stored person_credits into creator_credits entirely inside Postgres."""
    count = await db.scalar(
        text(
            """
            WITH source AS (
                SELECT CASE
                    WHEN jsonb_typeof(
                        metadata_json::jsonb -> 'raw_provider_payload' -> 'person_credits'
                    ) = 'array'
                    THEN metadata_json::jsonb -> 'raw_provider_payload' -> 'person_credits'
                    WHEN jsonb_typeof(metadata_json::jsonb -> 'person_credits') = 'array'
                    THEN metadata_json::jsonb -> 'person_credits'
                    ELSE NULL
                END AS credits
                FROM external_identities
                WHERE id = :identity_id
                  AND provider = 'comicvine'
                  AND entity_type = 'issue'
            ), updated AS (
                UPDATE external_identities ei
                SET metadata_json = (
                        ei.metadata_json::jsonb
                        || jsonb_build_object('creator_credits', source.credits)
                    )::json,
                    updated_at = CURRENT_TIMESTAMP
                FROM source
                WHERE ei.id = :identity_id
                  AND source.credits IS NOT NULL
                RETURNING source.credits
            )
            SELECT jsonb_array_length(credits)
            FROM updated
            """
        ),
        {"identity_id": identity_id},
    )
    if count is None:
        await db.rollback()
        return None
    await db.commit()
    return int(count)


async def _persist_deep_metadata(
    db: AsyncSession,
    *,
    identity_id: int,
    provider_result: dict[str, object],
) -> int:
    """Persist one validated singular issue payload and return creator count."""
    metadata = _normalize_issue_metadata(provider_result)
    external_url = _string(provider_result.get("site_detail_url"))
    provider_updated_at = _provider_timestamp(provider_result.get("date_last_updated"))
    await db.execute(
        text(
            """
            UPDATE external_identities
            SET external_url = COALESCE(:external_url, external_url),
                metadata_json = CAST(:metadata_json AS json),
                provider_updated_at = COALESCE(:provider_updated_at, provider_updated_at),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :identity_id
              AND provider = 'comicvine'
              AND entity_type = 'issue'
            """
        ),
        {
            "identity_id": identity_id,
            "external_url": external_url,
            "metadata_json": json.dumps(metadata),
            "provider_updated_at": provider_updated_at,
        },
    )
    await db.commit()
    return _creator_credit_count(metadata)


async def _confirmed_mapping_conflict(
    db: AsyncSession,
    *,
    issue_id: int,
    external_identity_id: int,
) -> bool:
    """Return whether another confirmed ComicVine issue identity already exists."""
    value = await db.scalar(
        text(
            """
            SELECT EXISTS(
                SELECT 1
                FROM issue_external_identity_mappings iem
                JOIN external_identities ei
                  ON ei.id = iem.external_identity_id
                WHERE iem.issue_id = :issue_id
                  AND iem.status = 'confirmed'
                  AND iem.external_identity_id <> :external_identity_id
                  AND ei.provider = 'comicvine'
            )
            """
        ),
        {"issue_id": issue_id, "external_identity_id": external_identity_id},
    )
    return bool(value)


async def _persist_resolved_mapping(
    db: AsyncSession,
    *,
    user_id: int,
    issue: ReadIssue,
    provider_row: dict[str, object],
    volume_id: int | None = None,
    volume_name: str | None = None,
    evidence_source: str = "series_volume_resolution",
) -> tuple[int, str] | None:
    """Persist one uniquely proven local or provider issue mapping."""
    provider_id = _integer(provider_row.get("id"))
    if provider_id is None:
        return None
    resolved_volume_id = volume_id if volume_id is not None else issue.series_volume_id
    resolved_volume_name = volume_name if volume_name is not None else issue.series_name

    owned = await db.scalar(
        text(
            """
            SELECT i.id
            FROM issues i
            JOIN threads t ON t.id = i.thread_id
            WHERE i.id = :issue_id
              AND t.user_id = :user_id
            FOR UPDATE OF i
            """
        ),
        {"issue_id": issue.issue_id, "user_id": user_id},
    )
    if owned is None:
        raise RuntimeError(f"issue {issue.issue_id} is not owned by user {user_id}")

    shallow_metadata: dict[str, object] = {
        "issue_number": _string(provider_row.get("issue_number")),
        "name": _string(provider_row.get("name")),
        "volume": _compact_reference(provider_row.get("volume")),
        "volume_id": resolved_volume_id,
        "volume_name": resolved_volume_name,
        "source": evidence_source,
    }
    external_url = _string(provider_row.get("site_detail_url"))
    identity_id = await db.scalar(
        text(
            """
            INSERT INTO external_identities (
                provider, entity_type, external_id, external_url, metadata_json,
                provider_updated_at, created_at, updated_at
            )
            VALUES (
                'comicvine', 'issue', :external_id, :external_url,
                CAST(:metadata_json AS json), NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (provider, entity_type, external_id)
            DO UPDATE SET
                external_url = COALESCE(EXCLUDED.external_url, external_identities.external_url),
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """
        ),
        {
            "external_id": str(provider_id),
            "external_url": external_url,
            "metadata_json": json.dumps(shallow_metadata),
        },
    )
    if identity_id is None:
        raise RuntimeError("failed to upsert resolved ComicVine identity")
    identity_id = int(identity_id)

    if await _confirmed_mapping_conflict(
        db,
        issue_id=issue.issue_id,
        external_identity_id=identity_id,
    ):
        await db.rollback()
        return None

    await db.execute(
        text(
            """
            INSERT INTO issue_external_identity_mappings (
                issue_id, external_identity_id, status, evidence_source,
                evidence_json, confidence, rejection_reason, created_at, updated_at
            )
            VALUES (
                :issue_id, :external_identity_id, 'confirmed',
                :evidence_source, CAST(:evidence_json AS json), 1.0, NULL,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (issue_id, external_identity_id)
            DO UPDATE SET
                status = 'confirmed',
                evidence_source = :evidence_source,
                evidence_json = CAST(:evidence_json AS json),
                confidence = 1.0,
                rejection_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "issue_id": issue.issue_id,
            "external_identity_id": identity_id,
            "evidence_source": evidence_source,
            "evidence_json": json.dumps(
                {
                    "thread_id": issue.thread_id,
                    "volume_id": resolved_volume_id,
                    "issue_label": issue.issue_number,
                }
            ),
        },
    )
    await db.commit()
    return identity_id, str(provider_id)


async def _resolve_unmapped_issue(
    db: AsyncSession,
    client: ComicVineClient,
    *,
    user_id: int,
    issue: ReadIssue,
) -> tuple[int, str] | None:
    """Resolve one unmapped issue only from confirmed-series exact-number evidence."""
    if issue.series_identity_id is None or issue.series_volume_id is None:
        return None
    if _is_ambiguous_special(issue.issue_number):
        return None

    expected = _normalize_issue_label(issue.issue_number)
    if not expected or not expected.isdigit():
        return None

    rows = await client.fetch_volume_issues(issue.series_volume_id)
    matches: dict[int, dict[str, object]] = {}
    for row in rows:
        row_label = _normalize_issue_label(_string(row.get("issue_number")))
        if row_label != expected:
            continue
        provider_id = _integer(row.get("id"))
        if provider_id is not None:
            matches.setdefault(provider_id, row)

    if len(matches) != 1:
        return None
    return await _persist_resolved_mapping(
        db,
        user_id=user_id,
        issue=issue,
        provider_row=next(iter(matches.values())),
    )


async def _provider_volume_issues(
    client: ComicVineClient,
    volume_id: int,
    cache: dict[int, list[dict[str, object]]],
) -> list[dict[str, object]]:
    """Fetch one provider volume roster once per command run."""
    if volume_id not in cache:
        cache[volume_id] = await client.fetch_volume_issues(volume_id)
    return cache[volume_id]


async def _provider_search_volume(
    client: ComicVineClient,
    title: str,
) -> dict[str, object] | None:
    """Find one exact-title/start-year provider volume without fuzzy promotion."""
    query_title, start_year = _title_search_hint(title)
    if start_year is None:
        return None
    response = await client.request(
        "search",
        "search",
        {
            "query": query_title,
            "resources": "volume",
            "limit": 20,
            "field_list": "id,name,publisher,start_year,count_of_issues,site_detail_url,image",
        },
    )
    rows = response.payload.get("results")
    if not isinstance(rows, list):
        return None
    expected_title = normalize_title(query_title)
    matches: dict[int, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        provider_id = _integer(row.get("id"))
        name = row.get("name")
        year = _integer(row.get("start_year"))
        if (
            provider_id is None
            or not isinstance(name, str)
            or year != start_year
            or normalize_title(name) != expected_title
        ):
            continue
        matches.setdefault(provider_id, row)
    if len(matches) != 1:
        return None
    return next(iter(matches.values()))


async def _resolve_provider_issue(
    db: AsyncSession,
    client: ComicVineClient,
    *,
    user_id: int,
    issue: ReadIssue,
    roster_cache: dict[int, list[dict[str, object]]],
) -> tuple[int, str] | None:
    """Resolve one remaining identity from provider evidence after local work is exhausted."""
    volume_ids = {
        volume_id
        for volume_id in (issue.series_volume_id, *issue.sibling_volume_ids)
        if volume_id is not None
    }
    if not volume_ids:
        search_row = await _provider_search_volume(client, issue.thread_title)
        if search_row is None:
            return None
        searched_volume_id = _integer(search_row.get("id"))
        if searched_volume_id is None:
            return None
        volume_ids = {searched_volume_id}

    candidates: list[tuple[int, int, dict[str, object]]] = []
    for volume_id in sorted(volume_ids):
        roster = await _provider_volume_issues(client, volume_id, roster_cache)
        for provider_id, row in _local_issue_matches(roster, issue.issue_number).items():
            candidates.append((volume_id, provider_id, row))
    if len(candidates) != 1:
        return None
    matched_volume_id, _provider_id, provider_row = candidates[0]
    volume_reference = provider_row.get("volume")
    volume_name = (
        volume_reference.get("name")
        if isinstance(volume_reference, dict)
        else issue.series_name
    )
    return await _persist_resolved_mapping(
        db,
        user_id=user_id,
        issue=issue,
        provider_row=provider_row,
        volume_id=matched_volume_id,
        volume_name=_string(volume_name),
        evidence_source="provider_volume_roster_resolution",
    )


async def _fetch_deep_metadata(
    db: AsyncSession,
    client: ComicVineClient,
    *,
    identity_id: int,
    external_id: str,
    refresh: bool,
) -> int:
    """Fetch, validate, and persist one singular ComicVine issue payload."""
    provider_id = _integer(external_id.removeprefix("4000-"))
    if provider_id is None:
        raise ValueError(f"invalid ComicVine issue external_id {external_id!r}")

    response = await client.fetch_issue(provider_id, refresh=refresh)
    result = response.payload.get("results")
    if not isinstance(result, dict):
        raise ComicVineError(f"ComicVine issue {provider_id} returned a non-object result")
    if _integer(result.get("id")) != provider_id:
        raise ComicVineError(
            f"ComicVine identity mismatch: requested {provider_id}, got {result.get('id')!r}"
        )
    return await _persist_deep_metadata(
        db,
        identity_id=identity_id,
        provider_result=result,
    )


async def _resolve_local_identity(
    db: AsyncSession,
    snapshot: LocalComicVineSnapshot,
    *,
    user_id: int,
    issue: ReadIssue,
    roster_cache: dict[int, list[dict[str, object]]],
    dry_run: bool,
) -> IdentityCandidate | None:
    """Resolve one issue from local evidence without constructing a provider client."""
    found = await _find_local_identity_candidate(snapshot, issue, roster_cache)
    if found is None:
        return None
    volume_id, provider_row = found
    provider_id = _integer(provider_row.get("id"))
    if provider_id is None:
        return None
    volume_reference = provider_row.get("volume")
    volume_name = (
        _string(volume_reference.get("name"))
        if isinstance(volume_reference, dict)
        else issue.series_name
    )
    if dry_run:
        return IdentityCandidate(
            identity_id=None,
            external_id=str(provider_id),
            volume_id=volume_id,
            volume_name=volume_name,
            source="comicvine-local-sqlite",
        )
    provider_row = dict(provider_row)
    provider_row.setdefault("volume", {"id": volume_id})
    persisted = await _persist_resolved_mapping(
        db,
        user_id=user_id,
        issue=issue,
        provider_row=provider_row,
        volume_id=volume_id,
        volume_name=volume_name,
        evidence_source="local_snapshot_exact_label_resolution",
    )
    if persisted is None:
        return None
    identity_id, external_id = persisted
    return IdentityCandidate(
        identity_id=identity_id,
        external_id=external_id,
        volume_id=volume_id,
        volume_name=volume_name,
        source="comicvine-local-sqlite",
    )


def _unmapped_result(
    issue: ReadIssue,
    *,
    status: str,
    phase: str,
    detail: str,
) -> BackfillResult:
    """Build a consistent result for an issue without an issue identity."""
    return BackfillResult(
        issue_id=issue.issue_id,
        thread_id=issue.thread_id,
        title=issue.thread_title,
        issue_number=issue.issue_number,
        status=status,
        phase=phase,
        detail=detail,
    )


async def _process_local_creator_issue(
    db: AsyncSession,
    snapshot: LocalComicVineSnapshot,
    *,
    issue: ReadIssue,
    dry_run: bool,
    refresh: bool,
) -> BackfillResult:
    """Process stored and SQLite creator work without making a provider request."""
    if issue.identity_id is None or issue.external_id is None:
        return _unmapped_result(
            issue,
            status="unmapped",
            phase="local-creators",
            detail="No confirmed ComicVine issue identity is available.",
        )
    if dry_run:
        local_payload = await _local_creator_payload(snapshot, issue.external_id)
        status = "complete" if issue.has_creator_credits else "planned-local"
        if not issue.has_creator_credits and not issue.has_person_credit_source and local_payload is None:
            status = "needs-hydration"
        return BackfillResult(
            issue_id=issue.issue_id,
            thread_id=issue.thread_id,
            title=issue.thread_title,
            issue_number=issue.issue_number,
            status=status,
            comicvine_issue_id=issue.external_id,
            creator_credits=issue.creator_credit_count,
            phase="local-creators",
            provenance="comicvine-local-sqlite" if local_payload is not None else "stored-metadata",
        )
    if refresh:
        return BackfillResult(
            issue_id=issue.issue_id,
            thread_id=issue.thread_id,
            title=issue.thread_title,
            issue_number=issue.issue_number,
            status="refresh-requested",
            comicvine_issue_id=issue.external_id,
            creator_credits=issue.creator_credit_count,
            phase="local-creators",
            provenance="stored-metadata",
        )
    if issue.has_creator_credits:
        return BackfillResult(
            issue_id=issue.issue_id,
            thread_id=issue.thread_id,
            title=issue.thread_title,
            issue_number=issue.issue_number,
            status="complete",
            comicvine_issue_id=issue.external_id,
            creator_credits=issue.creator_credit_count,
            phase="local-creators",
            provenance="stored-metadata",
        )

    creator_count = issue.creator_credit_count
    provenance = "stored-metadata"
    if issue.has_person_credit_source:
        normalized_count = await _normalize_existing_creator_credits(
            db,
            identity_id=issue.identity_id,
        )
        if normalized_count is not None:
            creator_count = normalized_count
            return BackfillResult(
                issue_id=issue.issue_id,
                thread_id=issue.thread_id,
                title=issue.thread_title,
                issue_number=issue.issue_number,
                status="complete",
                comicvine_issue_id=issue.external_id,
                creator_credits=creator_count,
                phase="local-creators",
                provenance=provenance,
            )

    local_payload = await _local_creator_payload(snapshot, issue.external_id)
    if local_payload is not None:
        creator_count = await _persist_deep_metadata(
            db,
            identity_id=issue.identity_id,
            provider_result=local_payload,
        )
        return BackfillResult(
            issue_id=issue.issue_id,
            thread_id=issue.thread_id,
            title=issue.thread_title,
            issue_number=issue.issue_number,
            status="complete",
            comicvine_issue_id=issue.external_id,
            creator_credits=creator_count,
            phase="local-creators",
            provenance="comicvine-local-sqlite",
        )
    return BackfillResult(
        issue_id=issue.issue_id,
        thread_id=issue.thread_id,
        title=issue.thread_title,
        issue_number=issue.issue_number,
        status="provider-dependent",
        comicvine_issue_id=issue.external_id,
        creator_credits=creator_count,
        phase="local-creators",
        detail="No stored or local creator payload is available.",
    )


async def _process_provider_creator_issue(
    db: AsyncSession,
    client: ComicVineClient | None,
    snapshot: LocalComicVineSnapshot,
    *,
    issue: ReadIssue,
    dry_run: bool,
    refresh: bool,
) -> BackfillResult:
    """Hydrate creator metadata after local identity work has been exhausted."""
    if issue.identity_id is None or issue.external_id is None:
        return _unmapped_result(
            issue,
            status="unmapped",
            phase="provider-creators",
            detail="No confirmed ComicVine issue identity is available.",
        )
    if dry_run:
        return BackfillResult(
            issue_id=issue.issue_id,
            thread_id=issue.thread_id,
            title=issue.thread_title,
            issue_number=issue.issue_number,
            status="complete" if issue.has_creator_credits else "planned-provider",
            comicvine_issue_id=issue.external_id,
            creator_credits=issue.creator_credit_count,
            phase="provider-creators",
            provenance="stored-metadata",
        )
    if not refresh and issue.has_creator_credits:
        return BackfillResult(
            issue_id=issue.issue_id,
            thread_id=issue.thread_id,
            title=issue.thread_title,
            issue_number=issue.issue_number,
            status="complete",
            comicvine_issue_id=issue.external_id,
            creator_credits=issue.creator_credit_count,
            phase="provider-creators",
            provenance="stored-metadata",
        )

    creator_count = issue.creator_credit_count
    if not refresh:
        if issue.has_person_credit_source:
            normalized_count = await _normalize_existing_creator_credits(
                db,
                identity_id=issue.identity_id,
            )
            if normalized_count is not None:
                creator_count = normalized_count
                return BackfillResult(
                    issue_id=issue.issue_id,
                    thread_id=issue.thread_id,
                    title=issue.thread_title,
                    issue_number=issue.issue_number,
                    status="complete",
                    comicvine_issue_id=issue.external_id,
                    creator_credits=creator_count,
                    phase="provider-creators",
                    provenance="stored-metadata",
                )
        local_payload = await _local_creator_payload(snapshot, issue.external_id)
        if local_payload is not None:
            creator_count = await _persist_deep_metadata(
                db,
                identity_id=issue.identity_id,
                provider_result=local_payload,
            )
            return BackfillResult(
                issue_id=issue.issue_id,
                thread_id=issue.thread_id,
                title=issue.thread_title,
                issue_number=issue.issue_number,
                status="complete",
                comicvine_issue_id=issue.external_id,
                creator_credits=creator_count,
                phase="provider-creators",
                provenance="comicvine-local-sqlite",
            )

    if client is None:
        return BackfillResult(
            issue_id=issue.issue_id,
            thread_id=issue.thread_id,
            title=issue.thread_title,
            issue_number=issue.issue_number,
            status="provider-dependent",
            comicvine_issue_id=issue.external_id,
            creator_credits=creator_count,
            phase="provider-creators",
            detail="COMICVINE_API_KEY is not configured.",
        )
    try:
        creator_count = await _fetch_deep_metadata(
            db,
            client,
            identity_id=issue.identity_id,
            external_id=issue.external_id,
            refresh=refresh,
        )
    except ComicVineRateLimitError as exc:
        return BackfillResult(
            issue_id=issue.issue_id,
            thread_id=issue.thread_id,
            title=issue.thread_title,
            issue_number=issue.issue_number,
            status="rate-limited",
            comicvine_issue_id=issue.external_id,
            creator_credits=creator_count,
            phase="provider-creators",
            provenance="comicvine-live",
            resource=exc.resource,
            detail=f"ComicVine issue metadata deferred: {exc}",
        )
    except (ComicVineError, TimeoutError, ValueError, RuntimeError) as exc:
        await db.rollback()
        return BackfillResult(
            issue_id=issue.issue_id,
            thread_id=issue.thread_id,
            title=issue.thread_title,
            issue_number=issue.issue_number,
            status="failed",
            comicvine_issue_id=issue.external_id,
            creator_credits=creator_count,
            phase="provider-creators",
            resource="issue",
            detail=f"{type(exc).__name__}: {exc}",
        )
    return BackfillResult(
        issue_id=issue.issue_id,
        thread_id=issue.thread_id,
        title=issue.thread_title,
        issue_number=issue.issue_number,
        status="complete",
        comicvine_issue_id=issue.external_id,
        creator_credits=creator_count,
        phase="provider-creators",
        provenance="comicvine-live-or-cache",
    )


async def _process_issue(
    db: AsyncSession,
    client: ComicVineClient | None,
    *,
    user_id: int,
    issue: ReadIssue,
    dry_run: bool,
    refresh: bool,
) -> BackfillResult:
    """Process one issue without guessing through ambiguous identity evidence."""
    identity_id = issue.identity_id
    external_id = issue.external_id
    has_creator_credits = issue.has_creator_credits
    has_person_credit_source = issue.has_person_credit_source
    creator_count = issue.creator_credit_count

    if identity_id is None or external_id is None:
        if dry_run:
            return BackfillResult(
                issue_id=issue.issue_id,
                thread_id=issue.thread_id,
                title=issue.thread_title,
                issue_number=issue.issue_number,
                status="unmapped",
                detail=(
                    "No confirmed ComicVine issue mapping. "
                    + (
                        "A confirmed series mapping exists."
                        if issue.series_identity_id is not None
                        else "No confirmed series mapping exists."
                    )
                ),
            )
        assert client is not None
        resolved = await _resolve_unmapped_issue(
            db,
            client,
            user_id=user_id,
            issue=issue,
        )
        if resolved is None:
            return BackfillResult(
                issue_id=issue.issue_id,
                thread_id=issue.thread_id,
                title=issue.thread_title,
                issue_number=issue.issue_number,
                status="unresolved",
                detail="Could not prove one unique ComicVine issue mapping.",
            )
        identity_id, external_id = resolved
        has_creator_credits = False
        has_person_credit_source = False
        creator_count = 0

    if dry_run:
        if has_creator_credits:
            status = "complete"
        elif has_person_credit_source:
            status = "needs-normalization"
        else:
            status = "needs-hydration"
        return BackfillResult(
            issue_id=issue.issue_id,
            thread_id=issue.thread_id,
            title=issue.thread_title,
            issue_number=issue.issue_number,
            status=status,
            comicvine_issue_id=external_id,
            creator_credits=creator_count,
        )

    if not refresh and not has_creator_credits and has_person_credit_source:
        normalized_count = await _normalize_existing_creator_credits(
            db,
            identity_id=identity_id,
        )
        if normalized_count is not None:
            has_creator_credits = True
            creator_count = normalized_count

    if refresh or not has_creator_credits:
        assert client is not None
        creator_count = await _fetch_deep_metadata(
            db,
            client,
            identity_id=identity_id,
            external_id=external_id,
            refresh=refresh,
        )
        has_creator_credits = True

    return BackfillResult(
        issue_id=issue.issue_id,
        thread_id=issue.thread_id,
        title=issue.thread_title,
        issue_number=issue.issue_number,
        status="complete" if has_creator_credits else "failed",
        comicvine_issue_id=external_id,
        creator_credits=creator_count,
        detail=None if has_creator_credits else "Creator metadata is still incomplete.",
    )


async def _run_local_identity_phase(
    db: AsyncSession,
    snapshot: LocalComicVineSnapshot,
    *,
    user_id: int,
    issues: list[ReadIssue],
    dry_run: bool,
) -> list[BackfillResult]:
    """Attempt every identity that can be proven from the local snapshot."""
    roster_cache: dict[int, list[dict[str, object]]] = {}
    results: list[BackfillResult] = []
    for issue in issues:
        if issue.identity_id is not None and issue.external_id is not None:
            result = BackfillResult(
                issue_id=issue.issue_id,
                thread_id=issue.thread_id,
                title=issue.thread_title,
                issue_number=issue.issue_number,
                status="already-mapped",
                comicvine_issue_id=issue.external_id,
                phase="local-identity",
                provenance="database",
            )
        else:
            try:
                candidate = await _resolve_local_identity(
                    db,
                    snapshot,
                    user_id=user_id,
                    issue=issue,
                    roster_cache=roster_cache,
                    dry_run=dry_run,
                )
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
                await db.rollback()
                result = _unmapped_result(
                    issue,
                    status="failed",
                    phase="local-identity",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            else:
                if candidate is None:
                    result = _unmapped_result(
                        issue,
                        status="deferred-local",
                        phase="local-identity",
                        detail="No unique identity was provable from local SQLite evidence.",
                    )
                else:
                    result = BackfillResult(
                        issue_id=issue.issue_id,
                        thread_id=issue.thread_id,
                        title=issue.thread_title,
                        issue_number=issue.issue_number,
                        status="planned-local" if dry_run else "resolved-local",
                        comicvine_issue_id=candidate.external_id,
                        phase="local-identity",
                        provenance=candidate.source,
                        detail="Identity proven from local ComicVine evidence.",
                    )
        results.append(result)
    return results


async def _run_provider_identity_phase(
    db: AsyncSession,
    client: ComicVineClient | None,
    *,
    user_id: int,
    issues: list[ReadIssue],
    dry_run: bool,
) -> list[BackfillResult]:
    """Attempt only identities left unresolved after the local phase."""
    roster_cache: dict[int, list[dict[str, object]]] = {}
    results: list[BackfillResult] = []
    for issue in issues:
        if issue.identity_id is not None and issue.external_id is not None:
            result = BackfillResult(
                issue_id=issue.issue_id,
                thread_id=issue.thread_id,
                title=issue.thread_title,
                issue_number=issue.issue_number,
                status="already-mapped",
                comicvine_issue_id=issue.external_id,
                phase="provider-identity",
                provenance="database",
            )
            results.append(result)
            continue
        if dry_run or client is None:
            result = _unmapped_result(
                issue,
                status="planned-provider" if dry_run else "provider-dependent",
                phase="provider-identity",
                detail=(
                    "Provider identity work is planned without a network call."
                    if dry_run
                    else "COMICVINE_API_KEY is not configured."
                ),
            )
            results.append(result)
            continue
        try:
            resolved = await _resolve_provider_issue(
                db,
                client,
                user_id=user_id,
                issue=issue,
                roster_cache=roster_cache,
            )
        except ComicVineRateLimitError as exc:
            result = _unmapped_result(
                issue,
                status="rate-limited",
                phase="provider-identity",
                detail=f"ComicVine identity work deferred: {exc}",
            )
            result.resource = exc.resource
        except (ComicVineError, OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            await db.rollback()
            result = _unmapped_result(
                issue,
                status="failed",
                phase="provider-identity",
                detail=f"{type(exc).__name__}: {exc}",
            )
        else:
            if resolved is None:
                result = _unmapped_result(
                    issue,
                    status="unresolved",
                    phase="provider-identity",
                    detail="Provider evidence did not prove one unique issue identity.",
                )
            else:
                result = BackfillResult(
                    issue_id=issue.issue_id,
                    thread_id=issue.thread_id,
                    title=issue.thread_title,
                    issue_number=issue.issue_number,
                    status="resolved-provider",
                    comicvine_issue_id=resolved[1],
                    phase="provider-identity",
                    provenance="comicvine-provider",
                )
        results.append(result)
    return results


async def _run_local_creator_phase(
    db: AsyncSession,
    snapshot: LocalComicVineSnapshot,
    *,
    issues: list[ReadIssue],
    dry_run: bool,
    refresh: bool,
) -> list[BackfillResult]:
    """Process all stored and SQLite-satisfiable creator work before provider work."""
    results: list[BackfillResult] = []
    for issue in issues:
        try:
            result = await _process_local_creator_issue(
                db,
                snapshot,
                issue=issue,
                dry_run=dry_run,
                refresh=refresh,
            )
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            await db.rollback()
            result = BackfillResult(
                issue_id=issue.issue_id,
                thread_id=issue.thread_id,
                title=issue.thread_title,
                issue_number=issue.issue_number,
                status="failed",
                phase="local-creators",
                detail=f"{type(exc).__name__}: {exc}",
            )
        results.append(result)
    return results


async def _run_provider_creator_phase(
    db: AsyncSession,
    client: ComicVineClient | None,
    snapshot: LocalComicVineSnapshot,
    *,
    issues: list[ReadIssue],
    dry_run: bool,
    refresh: bool,
) -> list[BackfillResult]:
    """Hydrate newly satisfiable creator data and continue past resource throttles."""
    results: list[BackfillResult] = []
    for issue in issues:
        try:
            result = await _process_provider_creator_issue(
                db,
                client,
                snapshot,
                issue=issue,
                dry_run=dry_run,
                refresh=refresh,
            )
        except (ComicVineRateLimitError, ComicVineError, OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            await db.rollback()
            result = BackfillResult(
                issue_id=issue.issue_id,
                thread_id=issue.thread_id,
                title=issue.thread_title,
                issue_number=issue.issue_number,
                status="failed",
                phase="provider-creators",
                detail=f"{type(exc).__name__}: {exc}",
            )
        results.append(result)
    return results


def _phase_report(
    name: str,
    results: list[BackfillResult],
    *,
    client: ComicVineClient | None,
) -> dict[str, object]:
    """Serialize one phase with stable counts and resource metadata."""
    statuses: dict[str, int] = {}
    for result in results:
        statuses[result.status] = statuses.get(result.status, 0) + 1
    return {
        "name": name,
        "processed": len(results),
        "statuses": dict(sorted(statuses.items())),
        "provider_requests": client.live_request_starts if client is not None else 0,
        "throttled_resources": sorted(
            {result.resource for result in results if result.resource is not None}
        ),
        "results": [asdict(result) for result in results],
    }


def _summarize(results: list[BackfillResult]) -> dict[str, object]:
    """Summarize per-issue outcomes for console and JSON reporting."""
    statuses: dict[str, int] = {}
    for result in results:
        statuses[result.status] = statuses.get(result.status, 0) + 1
    return {
        "processed": len(results),
        "statuses": dict(sorted(statuses.items())),
        "issues_with_creator_credits": sum(r.creator_credits > 0 for r in results),
        "creator_credit_rows": sum(r.creator_credits for r in results),
        "pending": sorted(
            result.issue_id
            for result in results
            if result.status in {"provider-dependent", "rate-limited", "unresolved", "failed"}
        ),
        "throttled_resources": sorted(
            {result.resource for result in results if result.resource is not None}
        ),
    }


def _write_report(path: Path, payload: dict[str, object]) -> None:
    """Atomically persist a machine-readable operator checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)



async def _run(args: argparse.Namespace) -> int:
    """Execute the complete local-first, resumable operator pipeline."""
    database_url = _require_database_url(args.database_url)
    host, database = _database_target(database_url)
    report_path = Path(args.report)
    user_id = args.user_id
    dry_run = bool(args.dry_run)
    refresh = bool(args.refresh)
    limit = args.limit
    api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
    snapshot = _local_snapshot_from_environment()
    engine = _engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    phases: list[dict[str, object]] = []
    final_results: list[BackfillResult] = []
    client: ComicVineClient | None = None
    interrupted = False

    def checkpoint() -> None:
        """Persist phase progress so an interrupted run remains auditable and resumable."""
        current = final_results or [
            BackfillResult(
                issue_id=0,
                thread_id=0,
                title="",
                issue_number="",
                status="not-started",
            )
        ]
        _write_report(
            report_path,
            {
                "version": 1,
                "user_id": user_id,
                "database": {"host": host, "database": database},
                "dry_run": dry_run,
                "refresh": refresh,
                "local_snapshot": {
                    "path": str(snapshot.path) if snapshot.path is not None else None,
                    "available": snapshot.available,
                },
                "api_key_configured": bool(api_key),
                "interrupted": interrupted,
                "phases": phases,
                "summary": _summarize(current),
                "issues": [asdict(result) for result in final_results],
            },
        )

    print(f"Database target: host={host} database={database}")
    print(
        "Local ComicVine snapshot: "
        f"{snapshot.path if snapshot.path is not None else 'not configured'}"
    )
    try:
        async with factory() as db:
            if not await _user_exists(db, user_id):
                raise SystemExit(
                    f"user_id={user_id} does not exist on "
                    f"host={host} database={database}; refusing to continue."
                )

            issues = await _load_read_issues(db, user_id=user_id, limit=limit)
            print(f"Found {len(issues)} read non-test issues for user_id={user_id}.")
            checkpoint()

            print("=== ComicVine stage 1/4: exhaust local identity evidence ===")
            local_identity = await _run_local_identity_phase(
                db,
                snapshot,
                user_id=user_id,
                issues=issues,
                dry_run=dry_run,
            )
            phases.append(_phase_report("local-identity", local_identity, client=client))
            checkpoint()
            issues = await _load_read_issues(db, user_id=user_id, limit=limit)

            print("=== ComicVine stage 2/4: exhaust stored/local creator metadata ===")
            local_creators = await _run_local_creator_phase(
                db,
                snapshot,
                issues=issues,
                dry_run=dry_run,
                refresh=refresh,
            )
            phases.append(_phase_report("local-creators", local_creators, client=client))
            checkpoint()
            issues = await _load_read_issues(db, user_id=user_id, limit=limit)

            if not dry_run and api_key:
                client = ComicVineClient(
                    api_key,
                    Path(os.environ.get("COMICVINE_CACHE_DIR", "/tmp/comicpile-comicvine")),
                    minimum_live_request_interval_seconds=OPERATOR_MINIMUM_LIVE_REQUEST_INTERVAL_SECONDS,
                    timeout_seconds=10.0,
                )
            elif not dry_run:
                print(
                    "COMICVINE_API_KEY is not configured; provider-dependent work will remain resumable."
                )

            print("=== ComicVine stage 3/4: provider-dependent identity leftovers ===")
            provider_identity = await _run_provider_identity_phase(
                db,
                client,
                user_id=user_id,
                issues=issues,
                dry_run=dry_run,
            )
            phases.append(_phase_report("provider-identity", provider_identity, client=client))
            checkpoint()
            issues = await _load_read_issues(db, user_id=user_id, limit=limit)

            print("=== ComicVine stage 4/4: hydrate newly satisfiable creator metadata ===")
            final_results = await _run_provider_creator_phase(
                db,
                client,
                snapshot,
                issues=issues,
                dry_run=dry_run,
                refresh=refresh,
            )
            phases.append(_phase_report("provider-creators", final_results, client=client))
    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
    finally:
        await engine.dispose()

    checkpoint()
    print(json.dumps(_summarize(final_results), indent=2, sort_keys=True))
    print(f"Report written to {report_path}")
    if interrupted:
        return 130
    return 1 if any(result.status == "failed" for result in final_results) else 0


def main() -> int:
    """Run the explicit-environment ComicVine backfill CLI."""
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
