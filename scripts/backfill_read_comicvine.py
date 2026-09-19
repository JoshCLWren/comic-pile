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
