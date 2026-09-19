#!/usr/bin/env python3
"""Run the complete ComicVine backfill for already-read ComicPile issues.

This is the single operator entrypoint. It runs two resumable internal phases:

1. resolve missing ComicVine issue identities at the series/thread level;
2. hydrate confirmed ComicVine issues with normalized creator metadata.

Both phases target the explicitly exported ``DATABASE_URL`` and share one
resource-aware ComicVine client. Creator hydration checks a local ComicVine
SQLite snapshot before spending a live ``/issue`` request, and processes all
stored/local-satisfiable creator work before provider-dependent leftovers. Live
requests are paced at 1.5 seconds between starts. HTTP 420/429 throttles block
only the affected ComicVine resource. When ComicVine supplies Retry-After, that
resource's deadline is honored. When it omits Retry-After, the operator uses a
per-resource exponential fallback of 60, 120, 240, 480, 960, 1920, then 3600
seconds. The fallback stays at one hour until that resource succeeds, then
resets to 60 seconds.

Examples:
    uv run python scripts/backfill_read_comicvine.py --user-id 1 --dry-run
    uv run python scripts/backfill_read_comicvine.py --user-id 1 --limit 25
    uv run python scripts/backfill_read_comicvine.py --user-id 1
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from types import ModuleType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comic_pile.comicvine_provider import (  # noqa: E402
    COMICVINE_BASE_URL,
    ComicVineClient as BaseComicVineClient,
    ComicVineError,
    ComicVineRateLimitError,
    ComicVineResponse,
)

CREATOR_HELPER = SCRIPT_DIR / "_backfill_read_comicvine_creators.py"
RESOLUTION_HELPER = SCRIPT_DIR / "resolve_read_comicvine_series.py"
DEFAULT_REPORT = Path("/tmp/comicpile-read-comicvine-backfill.json")
DEFAULT_RESOLUTION_REPORT = Path("/tmp/comicpile-read-comicvine-series-resolution.json")
DEFAULT_LOCAL_COMICVINE_DB = Path(
    "/mnt/bigdata/downloads/localcvdb_20260109/localcv.db"
)
OPERATOR_MINIMUM_LIVE_REQUEST_INTERVAL_SECONDS = 1.5
OPERATOR_FALLBACK_RETRY_AFTER_SECONDS = 60
OPERATOR_MAX_FALLBACK_RETRY_AFTER_SECONDS = 3600
LOCAL_VOLUME_CANDIDATE_LIMIT = 250
_LOCAL_DESCRIPTION_VOLUME_RE = re.compile(r"\b(?:volume|vol\.?)\s*(\d+)\b", re.IGNORECASE)


def _load_script_module(name: str, path: Path) -> ModuleType:
    """Load one internal operator helper without making scripts a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load operator helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_creator_helper = _load_script_module("_backfill_read_comicvine_creators", CREATOR_HELPER)

# Re-export creator helper implementation details so the existing focused tests
# continue to exercise the same logic through the public entrypoint.
for _name, _value in vars(_creator_helper).items():
    if _name.startswith("__") or _name in {"main", "DEFAULT_REPORT"}:
        continue
    globals().setdefault(_name, _value)


def _decode_local_list(value: object) -> list[object]:
    """Decode one JSON relationship array from the local ComicVine snapshot."""
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


def _local_alias_values(value: object) -> list[str]:
    """Return individual local volume aliases without treating the whole field as proof."""
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
    return [part.strip() for part in re.split(r"[\r\n|;]+", raw) if part.strip()]


def _description_volume_number(value: object) -> int | None:
    """Extract explicit local metadata such as ``Volume 1`` from a description."""
    if not isinstance(value, str):
        return None
    match = _LOCAL_DESCRIPTION_VOLUME_RE.search(value)
    return int(match.group(1)) if match is not None else None


class OperatorComicVineClient(BaseComicVineClient):
    """ComicVine client policy for long-running operator backfills."""

    def __init__(
        self,
        api_key: str,
        cache_dir: str | Path,
        *,
        local_db_path: str | Path | None = None,
        requests_per_hour: int | None = None,
        minimum_live_request_interval_seconds: float = (
            OPERATOR_MINIMUM_LIVE_REQUEST_INTERVAL_SECONDS
        ),
        base_url: str = COMICVINE_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Use local issue data first, then slower resource-aware live requests."""
        super().__init__(
            api_key,
            cache_dir,
            requests_per_hour=requests_per_hour,
            minimum_live_request_interval_seconds=minimum_live_request_interval_seconds,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
        self.local_db_path = Path(local_db_path) if local_db_path is not None else None
        self._local_db: sqlite3.Connection | None = None
        self._fallback_backoff_seconds: dict[str, int] = {}
        if self.local_db_path is not None and self.local_db_path.is_file():
            uri = f"file:{self.local_db_path}?mode=ro"
            self._local_db = sqlite3.connect(uri, uri=True)
            self._local_db.row_factory = sqlite3.Row
            print(f"Local ComicVine snapshot: {self.local_db_path}")

    def _fetch_local_issue(self, issue_id: int) -> ComicVineResponse | None:
        """Return one creator-capable local issue row without spending API quota."""
        if self._local_db is None:
            return None
        row = self._local_db.execute(
            """
            SELECT
                id,
                volume_id,
                name,
                issue_number,
                cover_date,
                store_date,
                image_url,
                site_detail_url,
                character_credits,
                person_credits,
                team_credits,
                story_arc_credits
            FROM cv_issue
            WHERE id = ?
            LIMIT 1
            """,
            (issue_id,),
        ).fetchone()
        if row is None:
            return None

        person_credits = _decode_local_list(row["person_credits"])
        if not person_credits:
            return None

        image_url = row["image_url"]
        payload: dict[str, object] = {
            "id": int(row["id"]),
            "name": row["name"],
            "issue_number": row["issue_number"],
            "cover_date": row["cover_date"],
            "store_date": row["store_date"],
            "image": {"original_url": image_url} if image_url else None,
            "volume": {"id": int(row["volume_id"])},
            "person_credits": person_credits,
            "character_credits": _decode_local_list(row["character_credits"]),
            "team_credits": _decode_local_list(row["team_credits"]),
            "story_arc_credits": _decode_local_list(row["story_arc_credits"]),
            "site_detail_url": row["site_detail_url"],
            "date_last_updated": None,
        }
        return ComicVineResponse(
            payload={"status_code": 1, "results": payload},
            from_cache=True,
            cache_key=f"localcv-issue-{issue_id}",
        )

    def has_local_issue(self, issue_id: int) -> bool:
        """Return whether the local snapshot can satisfy creator hydration."""
        return self._fetch_local_issue(issue_id) is not None

    def search_local_volumes(self, query_title: str) -> list[dict[str, object]]:
        """Use local FTS only to discover possible volumes, never to authorize one."""
        if self._local_db is None:
            return []
        normalized = query_title.casefold().replace("&", " and ")
        tokens = re.findall(r"[a-z0-9]+", normalized)
        if tokens and tokens[0] == "the":
            tokens = tokens[1:]
        if not tokens:
            return []
        fts_query = " AND ".join(f'"{token}"' for token in tokens)
        rows = self._local_db.execute(
            """
            SELECT
                v.id,
                v.name,
                v.aliases,
                v.start_year,
                v.publisher_id,
                v.count_of_issues,
                v.description,
                v.image_url,
                v.site_detail_url,
                p.name AS publisher_name
            FROM volume_fts
            JOIN cv_volume v ON v.id = volume_fts.rowid
            LEFT JOIN cv_publisher p ON p.id = v.publisher_id
            WHERE volume_fts MATCH ?
            ORDER BY bm25(volume_fts), v.id
            LIMIT ?
            """,
            (fts_query, LOCAL_VOLUME_CANDIDATE_LIMIT + 1),
        ).fetchall()
        candidates: list[dict[str, object]] = []
        for row in rows:
            publisher_id = int(row["publisher_id"]) if row["publisher_id"] is not None else None
            image_url = row["image_url"]
            candidates.append(
                {
                    "id": int(row["id"]),
                    "name": row["name"],
                    "aliases": row["aliases"],
                    "start_year": row["start_year"],
                    "count_of_issues": row["count_of_issues"],
                    "description": row["description"],
                    "publisher": (
                        {"id": publisher_id, "name": row["publisher_name"]}
                        if publisher_id is not None or row["publisher_name"] is not None
                        else None
                    ),
                    "image": {"medium_url": image_url} if image_url else None,
                    "site_detail_url": row["site_detail_url"],
                }
            )
        return candidates

    def _fetch_local_volume_issues(self, volume_id: int) -> list[dict[str, object]] | None:
        """Return a provider-shaped issue roster from the local snapshot when present."""
        if self._local_db is None:
            return None
        volume = self._local_db.execute(
            "SELECT id, name FROM cv_volume WHERE id = ? LIMIT 1",
            (volume_id,),
        ).fetchone()
        if volume is None:
            return None
        rows = self._local_db.execute(
            """
            SELECT id, name, issue_number, cover_date, store_date, site_detail_url
            FROM cv_issue
            WHERE volume_id = ?
            ORDER BY id
            """,
            (volume_id,),
        ).fetchall()
        if not rows:
            return None
        volume_ref = {"id": int(volume["id"]), "name": volume["name"]}
        return [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "issue_number": row["issue_number"],
                "cover_date": row["cover_date"],
                "store_date": row["store_date"],
                "site_detail_url": row["site_detail_url"],
                "volume": volume_ref,
            }
            for row in rows
        ]

    async def fetch_volume_issues(
        self,
        volume_id: int,
        *,
        refresh: bool = False,
    ) -> list[dict[str, object]]:
        """Prefer a complete local roster before spending a ComicVine volume request."""
        if not refresh:
            local = self._fetch_local_volume_issues(volume_id)
            if local is not None:
                return local
        return await super().fetch_volume_issues(volume_id, refresh=refresh)

    async def fetch_issue(
        self,
        issue_id: int,
        *,
        refresh: bool = False,
    ) -> ComicVineResponse:
        """Prefer the local snapshot, then cache/live ComicVine on a miss."""
        if not refresh:
            local = self._fetch_local_issue(issue_id)
            if local is not None:
                return local
        return await super().fetch_issue(issue_id, refresh=refresh)

    async def request(
        self,
        endpoint_bucket: str,
        endpoint: str,
        params: Mapping[str, object],
        *,
        refresh: bool = False,
    ) -> ComicVineResponse:
        """Retry throttled resources with Retry-After or exponential fallback."""
        while True:
            try:
                response = await super().request(
                    endpoint_bucket,
                    endpoint,
                    params,
                    refresh=refresh,
                )
                self._fallback_backoff_seconds.pop(endpoint_bucket, None)
                return response
            except ComicVineRateLimitError as exc:
                resource = exc.resource or endpoint_bucket
                delay = exc.retry_after_seconds
                if delay is None:
                    delay = self._fallback_backoff_seconds.get(
                        resource,
                        OPERATOR_FALLBACK_RETRY_AFTER_SECONDS,
                    )
                    self._fallback_backoff_seconds[resource] = min(
                        delay * 2,
                        OPERATOR_MAX_FALLBACK_RETRY_AFTER_SECONDS,
                    )
                    self._block_resource(resource, delay)
                    print(
                        f"ComicVine resource {resource!r} returned a throttle without "
                        f"Retry-After; backing off {delay}s before retrying this request."
                    )
                else:
                    print(
                        f"ComicVine resource {resource!r} is throttled for another "
                        f"{delay}s; retrying this request after the cooldown."
                    )
                await asyncio.sleep(max(1, delay))


def _local_candidate_has_exact_title(
    resolver: ModuleType,
    candidate: dict[str, object],
    *,
    query_title: str,
) -> bool:
    """Require exact normalized local name/alias equality after FTS discovery."""
    expected = resolver._normalize_series_title(query_title)
    values: list[str] = []
    name = candidate.get("name")
    if isinstance(name, str) and name.strip():
        values.append(name)
    values.extend(_local_alias_values(candidate.get("aliases")))
    return any(resolver._normalize_series_title(value) == expected for value in values)


def _local_year_distance(
    resolver: ModuleType,
    candidate: dict[str, object],
    *,
    start_year: int | None,
) -> int | None:
    """Return year distance as evidence without making year an identity key."""
    if start_year is None:
        return None
    candidate_year = resolver._integer(candidate.get("start_year"))
    return abs(candidate_year - start_year) if candidate_year is not None else None


def _select_local_evidence_candidate(
    resolver: ModuleType,
    *,
    hint: Any,
    candidates: list[dict[str, object]],
    rosters: dict[int, list[dict[str, object]]],
    issues: list[Any],
) -> dict[str, object] | None:
    """Select exactly one locally provable volume, or refuse to guess."""
    proven: list[dict[str, object]] = []
    for candidate in candidates:
        if not _local_candidate_has_exact_title(
            resolver,
            candidate,
            query_title=hint.query_title,
        ):
            continue
        volume_id = resolver._integer(candidate.get("id"))
        if volume_id is None or volume_id not in rosters:
            continue
        if not resolver._roster_uniquely_covers_all_issues(
            volume_id=volume_id,
            roster=rosters[volume_id],
            issues=issues,
        ):
            continue
        proven.append(candidate)

    if not proven:
        return None

    survivors = proven
    if hint.volume_hint is not None:
        explicit_matches = [
            candidate
            for candidate in survivors
            if _description_volume_number(candidate.get("description")) == hint.volume_hint
        ]
        if explicit_matches:
            survivors = explicit_matches
        else:
            survivors = [
                candidate
                for candidate in survivors
                if _description_volume_number(candidate.get("description")) is None
            ]

    if len(survivors) == 1:
        return survivors[0]

    if hint.start_year is not None:
        exact_year = [
            candidate
            for candidate in survivors
            if _local_year_distance(
                resolver,
                candidate,
                start_year=hint.start_year,
            )
            == 0
        ]
        if len(exact_year) == 1:
            return exact_year[0]
        if exact_year:
            survivors = exact_year
        else:
            near_year = [
                candidate
                for candidate in survivors
                if (
                    (distance := _local_year_distance(
                        resolver,
                        candidate,
                        start_year=hint.start_year,
                    ))
                    is not None
                    and distance <= 1
                )
            ]
            if len(near_year) == 1:
                return near_year[0]
            if near_year:
                survivors = near_year

    return survivors[0] if len(survivors) == 1 else None


async def _resolve_thread_from_local_evidence(
    resolver: ModuleType,
    db: AsyncSession,
    client: OperatorComicVineClient,
    *,
    user_id: int,
    work: Any,
    roster_cache: dict[int, list[dict[str, object]]],
) -> Any | None:
    """Resolve one previously-unanchored thread entirely from local ComicVine evidence."""
    _route, existing_volume_ids = resolver._classify_thread(work)
    if existing_volume_ids or client._local_db is None:
        return None

    hint = resolver._parse_title_hint(work.title)
    local_candidates = client.search_local_volumes(hint.query_title)
    if not local_candidates:
        return None
    if len(local_candidates) > LOCAL_VOLUME_CANDIDATE_LIMIT:
        return None

    rosters: dict[int, list[dict[str, object]]] = {}
    for candidate in local_candidates:
        if not _local_candidate_has_exact_title(
            resolver,
            candidate,
            query_title=hint.query_title,
        ):
            continue
        volume_id = resolver._integer(candidate.get("id"))
        if volume_id is None:
            continue
        roster = client._fetch_local_volume_issues(volume_id)
        if roster is not None:
            rosters[volume_id] = roster

    selected = _select_local_evidence_candidate(
        resolver,
        hint=hint,
        candidates=local_candidates,
        rosters=rosters,
        issues=work.issues,
    )
    if selected is None:
        return None

    volume_id = resolver._integer(selected.get("id"))
    if volume_id is None:
        return None
    roster = rosters[volume_id]
    roster_cache[volume_id] = roster
    evidence_source = (
        "local_snapshot_title_volume_roster_resolution"
        if hint.volume_hint is not None
        else "local_snapshot_title_roster_resolution"
    )
    await resolver._persist_thread_series(
        db,
        user_id=user_id,
        thread_id=work.thread_id,
        volume_id=volume_id,
        evidence_source=evidence_source,
        search_row=selected,
        evidence_name=resolver._string(selected.get("name")),
    )

    mapped = 0
    scoped_roster = {volume_id: roster}
    for issue in work.issues:
        matches = resolver._candidate_issue_rows(scoped_roster, issue.issue_number)
        if len(matches) != 1:
            continue
        _matched_volume_id, provider_row = matches[0]
        if await resolver._persist_issue_mapping(
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
    return resolver.ThreadResult(
        thread_id=work.thread_id,
        title=work.title,
        unresolved_before=len(work.issues),
        status="resolved" if remaining == 0 else ("partial" if mapped else "unresolved"),
        mapped=mapped,
        remaining=remaining,
        evidence="local-evidence",
        volume_ids=[volume_id],
        detail="Resolved from local ComicVine title/roster evidence without provider search.",
    )


def _parser() -> argparse.ArgumentParser:
    """Build the single public operator CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Resolve missing ComicVine identities, then backfill creator metadata "
            "for read ComicPile issues."
        )
    )
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL. Otherwise the exported DATABASE_URL is required.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inventory both phases without ComicVine calls or writes.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force creator metadata refresh for already-mapped ComicVine issues.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit creator-hydration issue processing after identity resolution.",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser


def _print_throttle(exc: ComicVineRateLimitError, announced: set[str]) -> None:
    """Explain a resource throttle once while allowing unrelated work to continue."""
    resource = exc.resource or "unknown"
    if resource in announced:
        return
    announced.add(resource)
    if exc.retry_after_seconds is None:
        print(
            f"ComicVine resource {resource!r} is throttled with no Retry-After. "
            "Skipping uncached requests for only that resource for the rest of this run."
        )
    else:
        print(
            f"ComicVine resource {resource!r} is throttled for another "
            f"{exc.retry_after_seconds}s. Other resources and cached responses will continue."
        )


def _write_report(path: Path, payload: dict[str, object]) -> None:
    """Write one deterministic operator report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Report written to {path}")


async def _run_resolution_phase(
    args: argparse.Namespace,
    resolver: ModuleType,
    *,
    database_url: str,
    client: OperatorComicVineClient | None,
) -> int:
    """Resolve identities without letting one resource throttle stop other routes."""
    host, database = resolver._database_target(database_url)
    print(f"Database target: host={host} database={database}")
    engine = resolver._engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    results: list[Any] = []
    roster_cache: dict[int, list[dict[str, object]]] = {}
    announced_throttles: set[str] = set()

    try:
        async with factory() as db:
            if not await resolver._user_exists(db, args.user_id):
                raise SystemExit(
                    f"user_id={args.user_id} does not exist on "
                    f"host={host} database={database}; refusing to continue."
                )

            works = await resolver._load_unresolved_threads(
                db,
                user_id=args.user_id,
                limit_threads=None,
            )
            unresolved_count = sum(len(work.issues) for work in works)
            print(
                f"Found {len(works)} unresolved threads containing "
                f"{unresolved_count} read issues for user_id={args.user_id}."
            )

            if args.dry_run:
                for work in works:
                    route, volume_ids = resolver._classify_thread(work)
                    result = resolver.ThreadResult(
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
                assert client is not None
                for index, work in enumerate(works, start=1):
                    print(f"[{index}/{len(works)}] {work.title} ({len(work.issues)} unresolved)")
                    try:
                        result = await _resolve_thread_from_local_evidence(
                            resolver,
                            db,
                            client,
                            user_id=args.user_id,
                            work=work,
                            roster_cache=roster_cache,
                        )
                        if result is None:
                            result = await resolver._resolve_thread(
                                db,
                                client,
                                user_id=args.user_id,
                                work=work,
                                roster_cache=roster_cache,
                            )
                    except ComicVineRateLimitError as exc:
                        result = resolver.ThreadResult(
                            thread_id=work.thread_id,
                            title=work.title,
                            unresolved_before=len(work.issues),
                            status="rate-limited",
                            remaining=len(work.issues),
                            detail=str(exc),
                        )
                        _print_throttle(exc, announced_throttles)
                    except (ComicVineError, TimeoutError, ValueError, RuntimeError) as exc:
                        await db.rollback()
                        result = resolver.ThreadResult(
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
    finally:
        await engine.dispose()

    summary = resolver._summary(results)
    report = {
        "user_id": args.user_id,
        "database": {"host": host, "database": database},
        "dry_run": args.dry_run,
        "summary": summary,
        "threads": [asdict(result) for result in results],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    _write_report(DEFAULT_RESOLUTION_REPORT, report)
    return 1 if any(result.status == "failed" for result in results) else 0


async def _run_creator_phase(
    args: argparse.Namespace,
    *,
    database_url: str,
    client: OperatorComicVineClient | None,
) -> int:
    """Hydrate all stored/local creator data before provider-dependent leftovers."""
    helper = _creator_helper
    host, database = helper._database_target(database_url)
    print(f"Database target: host={host} database={database}")
    engine = helper._engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    results: list[Any] = []
    announced_throttles: set[str] = set()

    try:
        async with factory() as db:
            if not await helper._user_exists(db, args.user_id):
                raise SystemExit(
                    f"user_id={args.user_id} does not exist on "
                    f"host={host} database={database}; refusing to continue."
                )

            issues = await helper._load_read_issues(db, user_id=args.user_id, limit=args.limit)
            print(f"Found {len(issues)} read non-test issues for user_id={args.user_id}.")

            if not args.dry_run and not args.refresh and client is not None:
                local_first: list[Any] = []
                provider_dependent: list[Any] = []
                for issue in issues:
                    if issue.has_creator_credits or issue.has_person_credit_source:
                        local_first.append(issue)
                        continue
                    provider_id = (
                        helper._integer(issue.external_id.removeprefix("4000-"))
                        if issue.external_id is not None
                        else None
                    )
                    if provider_id is not None and client.has_local_issue(provider_id):
                        local_first.append(issue)
                    else:
                        provider_dependent.append(issue)
                issues = [*local_first, *provider_dependent]
                print(
                    "Creator pass order: "
                    f"{len(local_first)} stored/local-satisfiable first; "
                    f"{len(provider_dependent)} provider-dependent deferred to the end."
                )

            for index, issue in enumerate(issues, start=1):
                print(f"[{index}/{len(issues)}] {issue.thread_title} #{issue.issue_number}")
                try:
                    result = await helper._process_issue(
                        db,
                        client,
                        user_id=args.user_id,
                        issue=issue,
                        dry_run=args.dry_run,
                        refresh=args.refresh,
                    )
                except ComicVineRateLimitError as exc:
                    result = helper.BackfillResult(
                        issue_id=issue.issue_id,
                        thread_id=issue.thread_id,
                        title=issue.thread_title,
                        issue_number=issue.issue_number,
                        status="rate-limited",
                        comicvine_issue_id=issue.external_id,
                        creator_credits=issue.creator_credit_count,
                        detail=str(exc),
                    )
                    _print_throttle(exc, announced_throttles)
                except (ComicVineError, TimeoutError, ValueError, RuntimeError) as exc:
                    await db.rollback()
                    result = helper.BackfillResult(
                        issue_id=issue.issue_id,
                        thread_id=issue.thread_id,
                        title=issue.thread_title,
                        issue_number=issue.issue_number,
                        status="failed",
                        comicvine_issue_id=issue.external_id,
                        creator_credits=issue.creator_credit_count,
                        detail=f"{type(exc).__name__}: {exc}",
                    )

                results.append(result)
                cv = (
                    f" cv={result.comicvine_issue_id}"
                    if result.comicvine_issue_id is not None
                    else ""
                )
                creators = (
                    f" creators={result.creator_credits}"
                    if result.comicvine_issue_id is not None
                    else ""
                )
                print(f"  -> {result.status}{cv}{creators}")
                if result.detail:
                    print(f"     {result.detail}")
    finally:
        await engine.dispose()

    summary = helper._summarize(results)
    report = {
        "user_id": args.user_id,
        "database": {"host": host, "database": database},
        "dry_run": args.dry_run,
        "refresh": args.refresh,
        "summary": summary,
        "issues": [asdict(result) for result in results],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    _write_report(args.report, report)
    return 1 if any(result.status == "failed" for result in results) else 0


async def _run_pipeline(args: argparse.Namespace) -> int:
    """Run both phases with one resource-aware provider client."""
    resolver = _load_script_module("_resolve_read_comicvine_series", RESOLUTION_HELPER)
    database_url = _creator_helper._require_database_url(args.database_url)
    api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
    if not args.dry_run and not api_key:
        raise SystemExit("COMICVINE_API_KEY is required for a live backfill.")

    client: OperatorComicVineClient | None = None
    if not args.dry_run:
        local_db_path = Path(
            os.environ.get("COMICVINE_LOCAL_DB", str(DEFAULT_LOCAL_COMICVINE_DB))
        )
        client = OperatorComicVineClient(
            api_key,
            Path(os.environ.get("COMICVINE_CACHE_DIR", "/tmp/comicpile-comicvine")),
            local_db_path=local_db_path,
            timeout_seconds=10.0,
        )

    print("=== ComicVine phase 1/2: resolve missing issue identities ===")
    resolution_exit = await _run_resolution_phase(
        args,
        resolver,
        database_url=database_url,
        client=client,
    )

    print("=== ComicVine phase 2/2: hydrate creator metadata ===")
    creator_exit = await _run_creator_phase(
        args,
        database_url=database_url,
        client=client,
    )
    return 1 if resolution_exit != 0 or creator_exit != 0 else 0


def main() -> int:
    """Run the complete resumable ComicVine backfill pipeline."""
    return asyncio.run(_run_pipeline(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())