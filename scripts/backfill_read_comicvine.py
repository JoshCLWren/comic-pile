#!/usr/bin/env python3
"""Run the complete ComicVine backfill for already-read ComicPile issues.

This is the single operator entrypoint. It runs two resumable internal phases:

1. resolve missing ComicVine issue identities at the series/thread level;
2. hydrate confirmed ComicVine issues with normalized creator metadata.

Both phases target the explicitly exported ``DATABASE_URL`` and share one
resource-aware ComicVine client. Live requests are paced at 1.5 seconds between
starts. HTTP 420/429 throttles block only the affected ComicVine resource. When
ComicVine supplies Retry-After, that resource's deadline is honored and
persisted across reruns while cached and unrelated resources remain usable.

Examples:
    uv run python scripts/backfill_read_comicvine.py --user-id 1 --dry-run
    uv run python scripts/backfill_read_comicvine.py --user-id 1 --limit 25
    uv run python scripts/backfill_read_comicvine.py --user-id 1
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType

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
)

CREATOR_HELPER = SCRIPT_DIR / "_backfill_read_comicvine_creators.py"
RESOLUTION_HELPER = SCRIPT_DIR / "resolve_read_comicvine_series.py"
DEFAULT_REPORT = Path("/tmp/comicpile-read-comicvine-backfill.json")
DEFAULT_RESOLUTION_REPORT = Path("/tmp/comicpile-read-comicvine-series-resolution.json")
OPERATOR_MINIMUM_LIVE_REQUEST_INTERVAL_SECONDS = 1.5


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


class OperatorComicVineClient(BaseComicVineClient):
    """ComicVine client policy for long-running operator backfills."""

    def __init__(
        self,
        api_key: str,
        cache_dir: str | Path,
        *,
        requests_per_hour: int | None = None,
        minimum_live_request_interval_seconds: float = (
            OPERATOR_MINIMUM_LIVE_REQUEST_INTERVAL_SECONDS
        ),
        base_url: str = COMICVINE_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(
            api_key,
            cache_dir,
            requests_per_hour=requests_per_hour,
            minimum_live_request_interval_seconds=minimum_live_request_interval_seconds,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
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
    results: list[object] = []
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
    """Hydrate creators while skipping only currently blocked provider resources."""
    helper = _creator_helper
    host, database = helper._database_target(database_url)
    print(f"Database target: host={host} database={database}")
    engine = helper._engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    results: list[object] = []
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
        client = OperatorComicVineClient(
            api_key,
            Path(os.environ.get("COMICVINE_CACHE_DIR", "/tmp/comicpile-comicvine")),
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
