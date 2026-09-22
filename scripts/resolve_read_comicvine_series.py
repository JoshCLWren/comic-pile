#!/usr/bin/env python3
"""Resolve missing ComicVine issue identities for already-read ComicPile issues.

This is Phase 2 of the read-comic creator backfill. The creator backfill can only
hydrate issues that have a confirmed ComicVine issue identity. This operator
fills more of those identities at the thread/series level so a later creator
hydration pass can hydrate credits for the newly confirmed rows.

The script is intentionally isolated from ``app.*`` and the Pydantic settings
stack. It reads the already-exported ``DATABASE_URL`` from the process
environment and never falls back to a local or test database.

Resolution is conservative and evidence-first:

* confirmed ComicVine series mappings are reused;
* otherwise, a thread may inherit provider volumes from confirmed sibling issue
  mappings;
* multiple sibling volumes are treated as per-issue candidates, not collapsed
  into one series;
* titles ending in either ``(YYYY)`` or ``(YYYY - YYYY/Present)`` provide an
  exact start-year search hint;
* when title + start-year search returns multiple exact volume candidates, their
  issue rosters are compared and a thread-level volume is accepted only when
  exactly one candidate uniquely covers every unresolved issue label;
* if multiple exact search candidates remain, individual issues may still map
  when their exact label is unique across the candidate rosters;
* issue mappings always require an exact provider issue-label match;
* ambiguous or unprovable rows remain unresolved.

The command is idempotent and resumable. ComicVine's persistent cache, paced
live requests, and per-endpoint rolling-hour limiter are reused.

Examples:
    uv run python scripts/resolve_read_comicvine_series.py --user-id 1 --dry-run
    uv run python scripts/resolve_read_comicvine_series.py --user-id 1 --limit-threads 20
    uv run python scripts/resolve_read_comicvine_series.py --user-id 1
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comic_pile.comicvine_provider import (  # noqa: E402
    ComicVineClient,
    ComicVineError,
    ComicVineRateLimitError,
)

DEFAULT_REPORT = Path("/tmp/comicpile-read-comicvine-series-resolution.json")
_YEAR_HINT_RE = re.compile(
    r"\s*\((?P<start>\d{4})(?:\s*-\s*(?:\d{4}|present))?\)\s*$",
    re.IGNORECASE,
)
_VOLUME_HINT_RE = re.compile(r"\s*\(vol\.?\s*(?P<volume>\d+)\)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class IssueWork:
    """One unresolved read issue inside a thread."""

    issue_id: int
    issue_number: str
    position: int


@dataclass(frozen=True)
class SeriesEvidence:
    """One ComicVine volume supported by existing database evidence."""

    volume_id: int
    name: str | None
    start_year: int | None
    source: str


@dataclass(frozen=True)
class TitleHint:
    """Series title metadata parsed from ComicPile's thread display title."""

    query_title: str
    start_year: int | None
    volume_hint: int | None


@dataclass
class ThreadWork:
    """One unresolved thread and the evidence available for resolving it."""

    thread_id: int
    title: str
    issues: list[IssueWork] = field(default_factory=list)
    confirmed_series: list[SeriesEvidence] = field(default_factory=list)
    sibling_volumes: list[SeriesEvidence] = field(default_factory=list)


@dataclass
class ThreadResult:
    """Machine-readable Phase 2 result for one thread."""

    thread_id: int
    title: str
    unresolved_before: int
    status: str
    mapped: int = 0
    remaining: int = 0
    evidence: str | None = None
    volume_ids: list[int] = field(default_factory=list)
    detail: str | None = None


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


def _engine(database_url: str) -> AsyncEngine:
    """Create one small explicit-URL engine for the operator process."""
    return create_async_engine(
        _async_url(database_url),
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )


def _integer(value: object) -> int | None:
    """Coerce a numeric provider value without accepting booleans."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _string(value: object) -> str | None:
    """Coerce a non-empty provider value to text."""
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        normalized = str(value).strip()
        return normalized or None
    return None


def _volume_id(external_id: object) -> int | None:
    """Normalize a ComicVine volume external identity into its numeric ID."""
    value = _string(external_id)
    if value is None:
        return None
    return _integer(value.removeprefix("4050-").strip())


def _normalize_issue_label(value: object) -> str:
    """Normalize an issue label for exact provider-roster comparison."""
    text_value = _string(value)
    if text_value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", text_value).strip()
    normalized = normalized.removeprefix("#").strip().casefold()
    return " ".join(normalized.split())


def _normalize_series_title(value: str) -> str:
    """Normalize punctuation/case while retaining title-token equality semantics."""
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("&", " and ")
    tokens = re.findall(r"[a-z0-9]+", normalized)
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    return " ".join(tokens)


def _parse_title_hint(title: str) -> TitleHint:
    """Extract a stable base title, optional volume label, and exact start year."""
    remaining = unicodedata.normalize("NFKC", title).strip()
    start_year: int | None = None
    volume_hint: int | None = None

    year_match = _YEAR_HINT_RE.search(remaining)
    if year_match is not None:
        start_year = int(year_match.group("start"))
        remaining = remaining[: year_match.start()].rstrip()

    volume_match = _VOLUME_HINT_RE.search(remaining)
    if volume_match is not None:
        volume_hint = int(volume_match.group("volume"))
        remaining = remaining[: volume_match.start()].rstrip()

    return TitleHint(
        query_title=remaining or title.strip(),
        start_year=start_year,
        volume_hint=volume_hint,
    )


def _compact_reference(value: object) -> dict[str, object] | None:
    """Keep stable fields from one provider relationship object."""
    if not isinstance(value, dict):
        return None
    allowed = ("id", "name", "api_detail_url", "site_detail_url")
    return {key: value[key] for key in allowed if key in value}


def _series_row_metadata(row: dict[str, object]) -> dict[str, object]:
    """Persist only bounded useful metadata from a ComicVine volume search row."""
    publisher = _compact_reference(row.get("publisher"))
    image = row.get("image") if isinstance(row.get("image"), dict) else None
    image_url = None
    if isinstance(image, dict):
        image_url = _string(image.get("medium_url")) or _string(image.get("small_url"))
    return {
        "id": _integer(row.get("id")),
        "name": _string(row.get("name")),
        "start_year": _string(row.get("start_year")),
        "count_of_issues": _integer(row.get("count_of_issues")),
        "publisher": publisher,
        "image_url": image_url,
        "site_detail_url": _string(row.get("site_detail_url")),
        "source": "thread_title_start_year_resolution",
    }


def _search_volume_candidates(
    rows: list[dict[str, object]],
    *,
    hint: TitleHint,
) -> list[dict[str, object]]:
    """Return exact normalized-title + exact-start-year provider volumes."""
    if hint.start_year is None:
        return []
    expected_title = _normalize_series_title(hint.query_title)
    matches: dict[int, dict[str, object]] = {}
    for row in rows:
        provider_id = _integer(row.get("id"))
        name = _string(row.get("name"))
        start_year = _integer(row.get("start_year"))
        if provider_id is None or name is None:
            continue
        if _normalize_series_title(name) != expected_title:
            continue
        if start_year != hint.start_year:
            continue
        matches.setdefault(provider_id, row)
    return list(matches.values())


def _unique_search_volume(
    rows: list[dict[str, object]],
    *,
    hint: TitleHint,
) -> dict[str, object] | None:
    """Accept one provider volume when exact title + year are already unique."""
    matches = _search_volume_candidates(rows, hint=hint)
    return matches[0] if len(matches) == 1 else None


def _candidate_issue_rows(
    rosters: dict[int, list[dict[str, object]]],
    issue_number: str,
) -> list[tuple[int, dict[str, object]]]:
    """Return unique exact-label issue candidates across candidate volumes."""
    expected = _normalize_issue_label(issue_number)
    if not expected:
        return []
    matches: dict[int, tuple[int, dict[str, object]]] = {}
    for volume_id, rows in rosters.items():
        for row in rows:
            if _normalize_issue_label(row.get("issue_number")) != expected:
                continue
            provider_id = _integer(row.get("id"))
            if provider_id is None:
                continue
            matches.setdefault(provider_id, (volume_id, row))
    return list(matches.values())


def _roster_uniquely_covers_all_issues(
    *,
    volume_id: int,
    roster: list[dict[str, object]],
    issues: list[IssueWork],
) -> bool:
    """Return whether one volume has exactly one provider row for every unresolved label."""
    if not issues:
        return False
    scoped = {volume_id: roster}
    return all(len(_candidate_issue_rows(scoped, issue.issue_number)) == 1 for issue in issues)


def _unique_full_coverage_search_volume(
    candidates: list[dict[str, object]],
    *,
    rosters: dict[int, list[dict[str, object]]],
    issues: list[IssueWork],
) -> dict[str, object] | None:
    """Disambiguate exact title/year candidates only through complete exact roster coverage."""
    full_coverage: list[dict[str, object]] = []
    for candidate in candidates:
        volume_id = _integer(candidate.get("id"))
        if volume_id is None or volume_id not in rosters:
            continue
        if _roster_uniquely_covers_all_issues(
            volume_id=volume_id,
            roster=rosters[volume_id],
            issues=issues,
        ):
            full_coverage.append(candidate)
    return full_coverage[0] if len(full_coverage) == 1 else None


def _classify_thread(work: ThreadWork) -> tuple[str, list[int]]:
    """Classify the best currently available deterministic resolution route."""
    volumes = {
        evidence.volume_id
        for evidence in [*work.confirmed_series, *work.sibling_volumes]
    }
    if len(volumes) == 1:
        return "existing-volume", sorted(volumes)
    if len(volumes) > 1:
        return "multi-volume", sorted(volumes)
    hint = _parse_title_hint(work.title)
    if hint.start_year is not None:
        return "title-year-search", []
    return "manual", []


def _parser() -> argparse.ArgumentParser:
    """Build the operator CLI parser."""
    parser = argparse.ArgumentParser(
        description="Resolve missing ComicVine issue identities for read ComicPile issues."
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
        help="Inventory deterministic resolution routes without provider calls or writes.",
    )
    parser.add_argument(
        "--limit-threads",
        type=int,
        default=None,
        help="Process at most this many unresolved threads in queue order.",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser


async def _user_exists(db: AsyncSession, user_id: int) -> bool:
    """Return whether the target user exists on the selected database."""
    value = await db.scalar(
        text("SELECT EXISTS(SELECT 1 FROM users WHERE id = :user_id)"),
        {"user_id": user_id},
    )
    return bool(value)


async def _load_unresolved_threads(
    db: AsyncSession,
    *,
    user_id: int,
    limit_threads: int | None,
) -> list[ThreadWork]:
    """Load read issues that still lack a confirmed ComicVine issue identity."""
    thread_limit_sql = ""
    params: dict[str, object] = {"user_id": user_id}
    if limit_threads is not None:
        thread_limit_sql = "LIMIT :limit_threads"
        params["limit_threads"] = limit_threads

    rows = (
        await db.execute(
            text(
                f"""
                WITH unresolved_threads AS (
                    SELECT t.id, MIN(t.queue_position) AS queue_position
                    FROM threads t
                    JOIN issues i ON i.thread_id = t.id
                    WHERE t.user_id = :user_id
                      AND t.is_test IS FALSE
                      AND i.status = 'read'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM issue_external_identity_mappings iem
                          JOIN external_identities ei
                            ON ei.id = iem.external_identity_id
                          WHERE iem.issue_id = i.id
                            AND iem.status = 'confirmed'
                            AND ei.provider = 'comicvine'
                            AND ei.entity_type = 'issue'
                      )
                    GROUP BY t.id
                    ORDER BY MIN(t.queue_position), t.id
                    {thread_limit_sql}
                )
                SELECT
                    t.id AS thread_id,
                    t.title,
                    i.id AS issue_id,
                    i.issue_number,
                    i.position
                FROM unresolved_threads ut
                JOIN threads t ON t.id = ut.id
                JOIN issues i ON i.thread_id = t.id
                WHERE i.status = 'read'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM issue_external_identity_mappings iem
                      JOIN external_identities ei
                        ON ei.id = iem.external_identity_id
                      WHERE iem.issue_id = i.id
                        AND iem.status = 'confirmed'
                        AND ei.provider = 'comicvine'
                        AND ei.entity_type = 'issue'
                  )
                ORDER BY ut.queue_position, t.id, i.position, i.id
                """
            ),
            params,
        )
    ).mappings().all()

    by_thread: dict[int, ThreadWork] = {}
    for row in rows:
        thread_id = int(row["thread_id"])
        work = by_thread.setdefault(
            thread_id,
            ThreadWork(thread_id=thread_id, title=str(row["title"])),
        )
        work.issues.append(
            IssueWork(
                issue_id=int(row["issue_id"]),
                issue_number=str(row["issue_number"]),
                position=int(row["position"]),
            )
        )

    works = list(by_thread.values())
    if not works:
        return works
    thread_ids = tuple(work.thread_id for work in works)

    confirmed_stmt = text(
        """
        SELECT
            tsm.thread_id,
            ei.external_id,
            COALESCE(ei.metadata_json::jsonb ->> 'name', ei.metadata_json::jsonb ->> 'volume_name')
                AS series_name,
            ei.metadata_json::jsonb ->> 'start_year' AS start_year
        FROM thread_external_series_mappings tsm
        JOIN external_identities ei ON ei.id = tsm.external_identity_id
        WHERE tsm.thread_id IN :thread_ids
          AND tsm.status = 'confirmed'
          AND ei.provider = 'comicvine'
          AND ei.entity_type = 'series'
        ORDER BY tsm.thread_id, ei.id
        """
    ).bindparams(bindparam("thread_ids", expanding=True))
    confirmed_rows = (
        await db.execute(confirmed_stmt, {"thread_ids": thread_ids})
    ).mappings().all()

    for row in confirmed_rows:
        volume_id = _volume_id(row["external_id"])
        if volume_id is None:
            continue
        work = by_thread[int(row["thread_id"])]
        work.confirmed_series.append(
            SeriesEvidence(
                volume_id=volume_id,
                name=_string(row["series_name"]),
                start_year=_integer(row["start_year"]),
                source="confirmed-series",
            )
        )

    sibling_stmt = text(
        """
        SELECT DISTINCT
            i.thread_id,
            COALESCE(
                ei.metadata_json::jsonb -> 'volume' ->> 'id',
                ei.metadata_json::jsonb ->> 'volume_id',
                ei.metadata_json::jsonb -> 'raw_provider_payload' -> 'volume' ->> 'id'
            ) AS volume_id_text,
            COALESCE(
                ei.metadata_json::jsonb -> 'volume' ->> 'name',
                ei.metadata_json::jsonb ->> 'volume_name',
                ei.metadata_json::jsonb -> 'raw_provider_payload' -> 'volume' ->> 'name'
            ) AS volume_name
        FROM issues i
        JOIN issue_external_identity_mappings iem
          ON iem.issue_id = i.id AND iem.status = 'confirmed'
        JOIN external_identities ei
          ON ei.id = iem.external_identity_id
         AND ei.provider = 'comicvine'
         AND ei.entity_type = 'issue'
        WHERE i.thread_id IN :thread_ids
        """
    ).bindparams(bindparam("thread_ids", expanding=True))
    sibling_rows = (
        await db.execute(sibling_stmt, {"thread_ids": thread_ids})
    ).mappings().all()

    seen_sibling: dict[int, set[int]] = {}
    for row in sibling_rows:
        volume_id = _integer(row["volume_id_text"])
        if volume_id is None:
            continue
        thread_id = int(row["thread_id"])
        seen = seen_sibling.setdefault(thread_id, set())
        if volume_id in seen:
            continue
        seen.add(volume_id)
        by_thread[thread_id].sibling_volumes.append(
            SeriesEvidence(
                volume_id=volume_id,
                name=_string(row["volume_name"]),
                start_year=None,
                source="sibling-volume",
            )
        )

    return works


async def _search_series_candidates(
    client: ComicVineClient,
    *,
    hint: TitleHint,
) -> list[dict[str, object]]:
    """Search ComicVine and retain all exact normalized-title + start-year volumes."""
    response = await client.request(
        "search",
        "search",
        {
            "query": hint.query_title,
            "resources": "volume",
            "limit": 20,
            "field_list": "id,name,publisher,start_year,count_of_issues,site_detail_url,image",
        },
    )
    rows = response.payload.get("results")
    if not isinstance(rows, list):
        return []
    candidates = [row for row in rows if isinstance(row, dict)]
    return _search_volume_candidates(candidates, hint=hint)


async def _fetch_roster(
    client: ComicVineClient,
    *,
    volume_id: int,
    cache: dict[int, list[dict[str, object]]],
) -> list[dict[str, object]]:
    """Fetch one volume roster once per process, in addition to provider disk caching."""
    if volume_id not in cache:
        cache[volume_id] = await client.fetch_volume_issues(volume_id)
    return cache[volume_id]


async def _persist_thread_series(
    db: AsyncSession,
    *,
    user_id: int,
    thread_id: int,
    volume_id: int,
    evidence_source: str,
    search_row: dict[str, object] | None,
    evidence_name: str | None,
) -> None:
    """Promote deterministic thread-level volume evidence when no conflict exists."""
    owned = await db.scalar(
        text(
            """
            SELECT id FROM threads
            WHERE id = :thread_id AND user_id = :user_id
            FOR UPDATE
            """
        ),
        {"thread_id": thread_id, "user_id": user_id},
    )
    if owned is None:
        raise RuntimeError(f"thread {thread_id} is not owned by user {user_id}")

    conflicting = await db.scalar(
        text(
            """
            SELECT EXISTS(
                SELECT 1
                FROM thread_external_series_mappings tsm
                JOIN external_identities ei ON ei.id = tsm.external_identity_id
                WHERE tsm.thread_id = :thread_id
                  AND tsm.status = 'confirmed'
                  AND ei.provider = 'comicvine'
                  AND ei.entity_type = 'series'
                  AND regexp_replace(ei.external_id, '^4050-', '') <> :volume_id
            )
            """
        ),
        {"thread_id": thread_id, "volume_id": str(volume_id)},
    )
    if bool(conflicting):
        await db.rollback()
        raise RuntimeError("refusing to add a conflicting confirmed ComicVine series mapping")

    metadata = (
        _series_row_metadata(search_row)
        if search_row is not None
        else {"id": volume_id, "name": evidence_name, "source": evidence_source}
    )
    external_url = _string(search_row.get("site_detail_url")) if search_row is not None else None
    identity_id = await db.scalar(
        text(
            """
            INSERT INTO external_identities (
                provider, entity_type, external_id, external_url, metadata_json,
                provider_updated_at, created_at, updated_at
            )
            VALUES (
                'comicvine', 'series', :external_id, :external_url,
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
            "external_id": str(volume_id),
            "external_url": external_url,
            "metadata_json": json.dumps(metadata),
        },
    )
    if identity_id is None:
        raise RuntimeError("failed to upsert ComicVine series identity")

    await db.execute(
        text(
            """
            INSERT INTO thread_external_series_mappings (
                thread_id, external_identity_id, status, evidence_source,
                confidence, created_at, updated_at
            )
            VALUES (
                :thread_id, :external_identity_id, 'confirmed', :evidence_source,
                1.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (thread_id, external_identity_id)
            DO UPDATE SET
                status = 'confirmed',
                evidence_source = EXCLUDED.evidence_source,
                confidence = 1.0,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "thread_id": thread_id,
            "external_identity_id": int(identity_id),
            "evidence_source": evidence_source,
        },
    )
    await db.commit()


async def _persist_issue_mapping(
    db: AsyncSession,
    *,
    user_id: int,
    work: ThreadWork,
    issue: IssueWork,
    volume_id: int,
    provider_row: dict[str, object],
    evidence_source: str,
) -> bool:
    """Persist one exact-label ComicVine issue mapping unless a confirmed conflict appeared."""
    provider_id = _integer(provider_row.get("id"))
    if provider_id is None:
        return False

    owned = await db.scalar(
        text(
            """
            SELECT i.id
            FROM issues i
            JOIN threads t ON t.id = i.thread_id
            WHERE i.id = :issue_id
              AND i.thread_id = :thread_id
              AND t.user_id = :user_id
            FOR UPDATE OF i
            """
        ),
        {
            "issue_id": issue.issue_id,
            "thread_id": work.thread_id,
            "user_id": user_id,
        },
    )
    if owned is None:
        raise RuntimeError(f"issue {issue.issue_id} is not owned by user {user_id}")

    volume = provider_row.get("volume")
    shallow_metadata = {
        "issue_number": _string(provider_row.get("issue_number")),
        "name": _string(provider_row.get("name")),
        "volume": _compact_reference(volume),
        "volume_id": volume_id,
        "volume_name": _string(volume.get("name")) if isinstance(volume, dict) else None,
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
        raise RuntimeError("failed to upsert ComicVine issue identity")
    identity_id = int(identity_id)

    conflicting = await db.scalar(
        text(
            """
            SELECT EXISTS(
                SELECT 1
                FROM issue_external_identity_mappings iem
                JOIN external_identities ei ON ei.id = iem.external_identity_id
                WHERE iem.issue_id = :issue_id
                  AND iem.status = 'confirmed'
                  AND ei.provider = 'comicvine'
                  AND ei.entity_type = 'issue'
                  AND iem.external_identity_id <> :external_identity_id
            )
            """
        ),
        {"issue_id": issue.issue_id, "external_identity_id": identity_id},
    )
    if bool(conflicting):
        await db.rollback()
        return False

    await db.execute(
        text(
            """
            INSERT INTO issue_external_identity_mappings (
                issue_id, external_identity_id, status, evidence_source,
                evidence_json, confidence, rejection_reason, created_at, updated_at
            )
            VALUES (
                :issue_id, :external_identity_id, 'confirmed', :evidence_source,
                CAST(:evidence_json AS json), 1.0, NULL,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (issue_id, external_identity_id)
            DO UPDATE SET
                status = 'confirmed',
                evidence_source = EXCLUDED.evidence_source,
                evidence_json = EXCLUDED.evidence_json,
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
                    "thread_id": work.thread_id,
                    "volume_id": volume_id,
                    "issue_label": issue.issue_number,
                }
            ),
        },
    )
    await db.commit()
    return True


async def _resolve_thread(
    db: AsyncSession,
    client: ComicVineClient,
    *,
    user_id: int,
    work: ThreadWork,
    roster_cache: dict[int, list[dict[str, object]]],
) -> ThreadResult:
    """Resolve as many issues as possible from deterministic thread-level evidence."""
    route, volume_ids = _classify_thread(work)
    evidence_source = route
    rosters: dict[int, list[dict[str, object]]] = {}
    search_ambiguity = False

    if route == "manual":
        return ThreadResult(
            thread_id=work.thread_id,
            title=work.title,
            unresolved_before=len(work.issues),
            status="unresolved",
            remaining=len(work.issues),
            evidence="manual",
            detail="No confirmed/sibling volume evidence and no exact start-year title hint.",
        )

    if route == "title-year-search":
        hint = _parse_title_hint(work.title)
        search_candidates = await _search_series_candidates(client, hint=hint)
        if not search_candidates:
            return ThreadResult(
                thread_id=work.thread_id,
                title=work.title,
                unresolved_before=len(work.issues),
                status="unresolved",
                remaining=len(work.issues),
                evidence="title-year-search",
                detail="ComicVine search found no exact normalized-title + start-year volume.",
            )

        candidate_by_volume = {
            volume_id: row
            for row in search_candidates
            if (volume_id := _integer(row.get("id"))) is not None
        }
        volume_ids = sorted(candidate_by_volume)
        if not volume_ids:
            raise ComicVineError("exact ComicVine search candidates had no numeric volume IDs")

        if len(volume_ids) > 1:
            for volume_id in volume_ids:
                rosters[volume_id] = await _fetch_roster(
                    client,
                    volume_id=volume_id,
                    cache=roster_cache,
                )
            selected = _unique_full_coverage_search_volume(
                search_candidates,
                rosters=rosters,
                issues=work.issues,
            )
            if selected is not None:
                selected_volume = _integer(selected.get("id"))
                if selected_volume is None:
                    raise ComicVineError("roster-selected ComicVine volume had no numeric ID")
                volume_ids = [selected_volume]
                rosters = {selected_volume: rosters[selected_volume]}
                evidence_source = "thread_title_start_year_roster_resolution"
                await _persist_thread_series(
                    db,
                    user_id=user_id,
                    thread_id=work.thread_id,
                    volume_id=selected_volume,
                    evidence_source=evidence_source,
                    search_row=selected,
                    evidence_name=_string(selected.get("name")),
                )
            else:
                search_ambiguity = True
                evidence_source = "title_year_candidate_exact_label_resolution"
        else:
            selected_volume = volume_ids[0]
            selected = candidate_by_volume[selected_volume]
            evidence_source = "thread_title_start_year_resolution"
            await _persist_thread_series(
                db,
                user_id=user_id,
                thread_id=work.thread_id,
                volume_id=selected_volume,
                evidence_source=evidence_source,
                search_row=selected,
                evidence_name=_string(selected.get("name")),
            )
    elif not work.confirmed_series and len(volume_ids) == 1:
        evidence = next(
            (item for item in work.sibling_volumes if item.volume_id == volume_ids[0]),
            None,
        )
        evidence_source = "sibling_issue_volume_resolution"
        await _persist_thread_series(
            db,
            user_id=user_id,
            thread_id=work.thread_id,
            volume_id=volume_ids[0],
            evidence_source=evidence_source,
            search_row=None,
            evidence_name=evidence.name if evidence is not None else None,
        )
    elif len(volume_ids) > 1:
        evidence_source = "multi_volume_exact_label_resolution"
    else:
        evidence_source = "confirmed_series_exact_label_resolution"

    for volume_id in volume_ids:
        if volume_id not in rosters:
            rosters[volume_id] = await _fetch_roster(
                client,
                volume_id=volume_id,
                cache=roster_cache,
            )

    mapped = 0
    for issue in work.issues:
        candidates = _candidate_issue_rows(rosters, issue.issue_number)
        if len(candidates) != 1:
            continue
        volume_id, provider_row = candidates[0]
        if await _persist_issue_mapping(
            db,
            user_id=user_id,
            work=work,
            issue=issue,
            volume_id=volume_id,
            provider_row=provider_row,
            evidence_source=evidence_source,
        ):
            mapped += 1

    remaining = len(work.issues) - mapped
    status = "resolved" if remaining == 0 else ("partial" if mapped else "unresolved")
    detail: str | None = None
    if search_ambiguity and mapped == 0:
        detail = (
            "Multiple exact title/year volumes remained ambiguous after exact roster comparison."
        )
    elif search_ambiguity and remaining:
        detail = "Mapped only issue labels unique across exact title/year candidate rosters."
    elif mapped == 0:
        detail = "No unresolved issue had exactly one exact-label provider match."

    return ThreadResult(
        thread_id=work.thread_id,
        title=work.title,
        unresolved_before=len(work.issues),
        status=status,
        mapped=mapped,
        remaining=remaining,
        evidence=route,
        volume_ids=volume_ids,
        detail=detail,
    )


def _summary(results: list[ThreadResult]) -> dict[str, object]:
    """Summarize thread and issue outcomes."""
    statuses: dict[str, int] = {}
    for result in results:
        statuses[result.status] = statuses.get(result.status, 0) + 1
    return {
        "threads_processed": len(results),
        "threads_by_status": dict(sorted(statuses.items())),
        "issues_unresolved_before": sum(result.unresolved_before for result in results),
        "issues_mapped": sum(result.mapped for result in results),
        "issues_remaining": sum(result.remaining for result in results),
    }


async def _run(args: argparse.Namespace) -> int:
    """Execute one explicit-target Phase 2 resolution pass."""
    database_url = _require_database_url(args.database_url)
    host, database = _database_target(database_url)
    print(f"Database target: host={host} database={database}")

    api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
    if not args.dry_run and not api_key:
        raise SystemExit("COMICVINE_API_KEY is required for a live resolution pass.")

    engine = _engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    results: list[ThreadResult] = []
    roster_cache: dict[int, list[dict[str, object]]] = {}

    try:
        async with factory() as db:
            if not await _user_exists(db, args.user_id):
                raise SystemExit(
                    f"user_id={args.user_id} does not exist on "
                    f"host={host} database={database}; refusing to continue."
                )

            works = await _load_unresolved_threads(
                db,
                user_id=args.user_id,
                limit_threads=args.limit_threads,
            )
            unresolved_count = sum(len(work.issues) for work in works)
            print(
                f"Found {len(works)} unresolved threads containing "
                f"{unresolved_count} read issues for user_id={args.user_id}."
            )

            if args.dry_run:
                for work in works:
                    route, volume_ids = _classify_thread(work)
                    result = ThreadResult(
                        thread_id=work.thread_id,
                        title=work.title,
                        unresolved_before=len(work.issues),
                        status="planned",
                        remaining=len(work.issues),
                        evidence=route,
                        volume_ids=volume_ids,
                    )
                    results.append(result)
                    print(
                        f"[{len(results)}/{len(works)}] {work.title}: "
                        f"{len(work.issues)} unresolved -> {route}"
                    )
            else:
                client = ComicVineClient(
                    api_key,
                    Path(
                        os.environ.get(
                            "COMICVINE_CACHE_DIR",
                            "/tmp/comicpile-comicvine",
                        )
                    ),
                    timeout_seconds=10.0,
                )
                for index, work in enumerate(works, start=1):
                    print(f"[{index}/{len(works)}] {work.title} ({len(work.issues)} unresolved)")
                    try:
                        result = await _resolve_thread(
                            db,
                            client,
                            user_id=args.user_id,
                            work=work,
                            roster_cache=roster_cache,
                        )
                    except ComicVineRateLimitError as exc:
                        result = ThreadResult(
                            thread_id=work.thread_id,
                            title=work.title,
                            unresolved_before=len(work.issues),
                            status="rate-limited",
                            remaining=len(work.issues),
                            detail=str(exc),
                        )
                    except (ComicVineError, TimeoutError, ValueError, RuntimeError) as exc:
                        await db.rollback()
                        result = ThreadResult(
                            thread_id=work.thread_id,
                            title=work.title,
                            unresolved_before=len(work.issues),
                            status="failed",
                            remaining=len(work.issues),
                            detail=f"{type(exc).__name__}: {exc}",
                        )

                    results.append(result)
                    volumes = f" volumes={result.volume_ids}" if result.volume_ids else ""
                    print(
                        f"  -> {result.status}: mapped={result.mapped} "
                        f"remaining={result.remaining}{volumes}"
                    )
                    if result.detail:
                        print(f"     {result.detail}")
                    if result.status == "rate-limited":
                        print(
                            "ComicVine rate limit reached. Stopping cleanly; "
                            "rerun the same command later."
                        )
                        break
    finally:
        await engine.dispose()

    report = {
        "user_id": args.user_id,
        "database": {"host": host, "database": database},
        "dry_run": args.dry_run,
        "summary": _summary(results),
        "threads": [asdict(result) for result in results],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(f"Report written to {args.report}")

    return 1 if any(result.status == "failed" for result in results) else 0


def main() -> int:
    """Run the explicit-environment ComicVine series-first resolution CLI."""
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
