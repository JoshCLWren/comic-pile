"""Generate a read-only ComicVine hydration report for one ComicPile user."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from app.database import AsyncSessionLocal
from comic_pile.comicvine_hydrator import (
    apply_local_volume_segments,
    build_report,
    enumerate_user_issues,
    load_volume_segments,
    write_report,
)
from comic_pile.comicvine_live_refresh import refresh_confirmed_local_misses
from comic_pile.comicvine_provider import ComicVineClient, DEFAULT_REQUESTS_PER_HOUR
from comic_pile.local_comicvine import LocalComicVineSnapshot


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed CLI arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Inspect existing ComicPile issues against confirmed ComicVine identities "
            "and a read-only local ComicVine snapshot."
        )
    )
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--comicvine-db", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--segment-map",
        type=Path,
        help=(
            "Optional JSON file mapping ComicPile thread position ranges to confirmed "
            "ComicVine volume IDs for issue-level composite-thread hydration."
        ),
    )
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/comicvine-hydrator"))
    parser.add_argument(
        "--requests-per-hour",
        type=int,
        default=DEFAULT_REQUESTS_PER_HOUR,
        help="Per-endpoint rolling request ceiling; defaults to the conservative provider budget.",
    )
    parser.add_argument(
        "--live-refresh",
        action="store_true",
        help="Use cached/live ComicVine issue requests for confirmed identities missing locally.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass successful response cache entries during --live-refresh.",
    )
    parser.add_argument("--include-test-threads", action="store_true")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    """Build and persist one read-only hydration report.

    Args:
        args: Parsed CLI arguments.
    """
    snapshot = LocalComicVineSnapshot(args.comicvine_db)
    async with AsyncSessionLocal() as db:
        targets = await enumerate_user_issues(
            db,
            user_id=args.user_id,
            include_test_threads=args.include_test_threads,
        )

    if args.segment_map is not None:
        segments = load_volume_segments(args.segment_map)
        targets = await apply_local_volume_segments(targets, snapshot, segments)

    report = await build_report(targets, snapshot)

    if args.live_refresh:
        api_key = os.environ.get("COMICVINE_API_KEY", "")
        if not api_key.strip():
            raise RuntimeError("COMICVINE_API_KEY is required when --live-refresh is enabled")
        client = ComicVineClient(
            api_key,
            args.cache_dir,
            requests_per_hour=args.requests_per_hour,
        )
        await refresh_confirmed_local_misses(report, client, refresh=args.force_refresh)

    write_report(report, args.output)


def main() -> None:
    """Run the hydration report command."""
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
