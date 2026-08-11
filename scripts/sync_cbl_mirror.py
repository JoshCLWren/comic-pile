#!/usr/bin/env python3
"""Synchronize a local CBL mirror into normalized ComicPile reference tables."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys

from app.cbl_ingest import parse_cbl_mirror
from app.cbl_sync import sync_cbl_lists
from app.database import AsyncSessionLocal

DEFAULT_REPOSITORY = "JoshCLWren/CBL-ReadingLists"


def _parser() -> argparse.ArgumentParser:
    """Build command-line arguments for the CBL sync utility."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mirror_path", type=Path, help="Local root of the CBL mirror")
    parser.add_argument(
        "--repository",
        default=DEFAULT_REPOSITORY,
        help=f"Stable source repository identity (default: {DEFAULT_REPOSITORY})",
    )
    parser.add_argument(
        "--revision-sha",
        required=True,
        help="Source mirror revision SHA recorded with this synchronization",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report inserts, updates, deactivations, and parse failures without writes",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    """Parse the mirror, synchronize valid lists, and emit one JSON summary."""
    parsed, failures = parse_cbl_mirror(args.mirror_path)
    async with AsyncSessionLocal() as db:
        async with db.begin():
            summary = await sync_cbl_lists(
                db,
                repository=args.repository,
                revision_sha=args.revision_sha,
                parsed_lists=parsed,
                dry_run=args.dry_run,
            )

    payload = {
        **asdict(summary),
        "parsed_lists": len(parsed),
        "parse_failures": [asdict(failure) for failure in failures],
    }
    print(json.dumps(payload, sort_keys=True))
    return 1 if failures else 0


def main() -> int:
    """Run the asynchronous CBL mirror sync command."""
    args = _parser().parse_args()
    if not args.mirror_path.is_dir():
        print(
            json.dumps(
                {
                    "error": "mirror_path_not_directory",
                    "mirror_path": str(args.mirror_path),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
