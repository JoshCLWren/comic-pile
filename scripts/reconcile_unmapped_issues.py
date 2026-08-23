"""Run one bounded backfill pass for unmapped ComicVine issue identities.

Sweeps unread/reading issues lacking a confirmed provider mapping,
prioritizing active next-unread gaps, then threads with confirmed series.
Issues in threads with a confirmed series are resolved through the
deterministic series resolver; nothing is auto-confirmed ambiguously and no
pseudo-identities are fabricated.

Requires the standard application database configuration (DATABASE_URL or
TEST_DATABASE_URL) and, for provider-backed resolution, COMICVINE_API_KEY.

Example:
    uv run python scripts/reconcile_unmapped_issues.py --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
import json

from app.database import AsyncSessionLocal
from app.services.catalog import reconcile_unmapped_issues


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list to parse; defaults to sys.argv[1:].

    Returns:
        Parsed CLI arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Bounded backfill reconciliation for issues without confirmed "
            "ComicVine identities."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of issues to process in this bounded pass.",
    )
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> dict[str, int]:
    """Execute one bounded reconciliation pass.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Dict with counts: confirmed, candidate, unresolved, skipped.
    """
    async with AsyncSessionLocal() as db:
        return await reconcile_unmapped_issues(db, limit=args.limit)


def main() -> None:
    """Run the reconciliation command and print the outcome counts."""
    counts = asyncio.run(run(parse_args()))
    print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()
