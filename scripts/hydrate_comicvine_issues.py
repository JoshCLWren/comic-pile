"""Generate a read-only ComicVine hydration report for one ComicPile user."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.database import AsyncSessionLocal
from comic_pile.comicvine_hydrator import build_report, enumerate_user_issues, write_report
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
    write_report(build_report(targets, snapshot), args.output)


def main() -> None:
    """Run the hydration report command."""
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
