#!/usr/bin/env python3
"""Run the complete ComicVine backfill for already-read ComicPile issues.

This is the single operator entrypoint. It runs two resumable internal phases:

1. resolve missing ComicVine issue identities at the series/thread level;
2. hydrate confirmed ComicVine issues with normalized creator metadata.

Both phases target the explicitly exported ``DATABASE_URL`` and share the
persistent ComicVine response cache. Live requests are paced at 1.5 seconds
between starts. ComicVine HTTP 420 and 429 responses are treated as provider
throttles, causing the pipeline to stop cleanly so the same command can be
rerun later.

Examples:
    uv run python scripts/backfill_read_comicvine.py --user-id 1 --dry-run
    uv run python scripts/backfill_read_comicvine.py --user-id 1 --limit 25
    uv run python scripts/backfill_read_comicvine.py --user-id 1
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from types import ModuleType

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

# Re-export the creator helper's implementation details so the existing focused
# regression tests continue to exercise the same logic through the public entrypoint.
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

    def _request_sync(self, endpoint: str, params: Mapping[str, object]) -> dict[str, object]:
        """Treat ComicVine's HTTP 420 throttle response like HTTP 429."""
        try:
            return super()._request_sync(endpoint, params)
        except ComicVineRateLimitError:
            raise
        except ComicVineError as exc:
            if "ComicVine HTTP 420" in str(exc):
                raise ComicVineRateLimitError("ComicVine returned HTTP 420") from exc
            raise


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


def _resolution_was_rate_limited(report_path: Path) -> bool:
    """Return whether the identity phase stopped on a provider throttle."""
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return False
    statuses = summary.get("threads_by_status")
    if not isinstance(statuses, dict):
        return False
    rate_limited = statuses.get("rate-limited")
    return isinstance(rate_limited, int) and rate_limited > 0


async def _run_pipeline(args: argparse.Namespace) -> int:
    """Run identity resolution first, then creator hydration."""
    resolver = _load_script_module("_resolve_read_comicvine_series", RESOLUTION_HELPER)
    resolver.ComicVineClient = OperatorComicVineClient
    _creator_helper.ComicVineClient = OperatorComicVineClient

    resolution_args = argparse.Namespace(
        user_id=args.user_id,
        database_url=args.database_url,
        dry_run=args.dry_run,
        limit_threads=None,
        report=DEFAULT_RESOLUTION_REPORT,
    )

    print("=== ComicVine phase 1/2: resolve missing issue identities ===")
    resolution_exit = await resolver._run(resolution_args)
    if resolution_exit != 0:
        return int(resolution_exit)
    if not args.dry_run and _resolution_was_rate_limited(DEFAULT_RESOLUTION_REPORT):
        print(
            "ComicVine throttled identity resolution. Creator hydration is deferred; "
            "rerun this same command later."
        )
        return 0

    creator_args = argparse.Namespace(
        user_id=args.user_id,
        database_url=args.database_url,
        dry_run=args.dry_run,
        refresh=args.refresh,
        limit=args.limit,
        report=args.report,
    )

    print("=== ComicVine phase 2/2: hydrate creator metadata ===")
    return int(await _creator_helper._run(creator_args))


def main() -> int:
    """Run the complete resumable ComicVine backfill pipeline."""
    return asyncio.run(_run_pipeline(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
