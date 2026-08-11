"""Generate a read-only ComicVine hydration report for one ComicPile user."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from app.database import AsyncSessionLocal
from comic_pile.comicvine_deep_hydration import hydrate_deep_metadata
from comic_pile.comicvine_hydrator import (
    apply_cbl_issue_identities,
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
            "Inspect existing ComicPile issues against confirmed/CBL ComicVine identities "
            "and a read-only local ComicVine snapshot."
        )
    )
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument(
        "--cbl-mirror",
        type=Path,
        help=(
            "Optional CBL mirror root. Exact embedded ComicVine issue IDs are applied before "
            "local volume-segment or live provider discovery."
        ),
    )
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
        "--deep-hydration",
        action="store_true",
        help=(
            "Fetch full singular ComicVine issue metadata for matched confirmed identities and "
            "store it only in the generated report."
        ),
    )
    parser.add_argument(
        "--hydrate-story-arcs",
        action="store_true",
        help=(
            "With --deep-hydration, fetch each unique story arc discovered from issue metadata "
            "at most once per pass."
        ),
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass successful response cache entries during live or deep hydration.",
    )
    parser.add_argument("--include-test-threads", action="store_true")
    args = parser.parse_args()
    if args.hydrate_story_arcs and not args.deep_hydration:
        parser.error("--hydrate-story-arcs requires --deep-hydration")
    return args


def _provider_client(args: argparse.Namespace) -> ComicVineClient:
    """Build the shared endpoint-budgeted provider client for network-enabled modes."""
    api_key = os.environ.get("COMICVINE_API_KEY", "")
    if not api_key.strip():
        raise RuntimeError(
            "COMICVINE_API_KEY is required when live or deep ComicVine hydration is enabled"
        )
    return ComicVineClient(
        api_key,
        args.cache_dir,
        requests_per_hour=args.requests_per_hour,
    )


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

    if args.cbl_mirror is not None:
        targets = await apply_cbl_issue_identities(targets, args.cbl_mirror)

    if args.segment_map is not None:
        segments = load_volume_segments(args.segment_map)
        targets = await apply_local_volume_segments(targets, snapshot, segments)

    report = await build_report(targets, snapshot)
    client: ComicVineClient | None = None
    if args.live_refresh or args.deep_hydration:
        client = _provider_client(args)

    if args.live_refresh:
        assert client is not None
        await refresh_confirmed_local_misses(report, client, refresh=args.force_refresh)

    if args.deep_hydration:
        assert client is not None
        await hydrate_deep_metadata(
            report,
            client,
            hydrate_story_arcs=args.hydrate_story_arcs,
            refresh=args.force_refresh,
        )

    write_report(report, args.output)


def main() -> None:
    """Run the hydration report command."""
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
