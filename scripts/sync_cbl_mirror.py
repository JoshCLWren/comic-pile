#!/usr/bin/env python3
"""Inventory or synchronize a local CBL mirror into ComicPile reference tables."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys

from app.cbl_ingest import build_cbl_inventory, parse_cbl_mirror
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
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help=(
            "Print the complete mirror inventory without opening a database session; "
            "exit 1 when any file failed to parse"
        ),
    )
    parser.add_argument(
        "--reconcile-repository",
        action="append",
        default=[],
        metavar="REPOSITORY",
        help=(
            "Rename an existing legacy source identity to --repository in place, "
            "preserving its source and list IDs (may be repeated)"
        ),
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    """Parse the mirror, synchronize valid lists, and emit one JSON summary."""
    parsed, failures = parse_cbl_mirror(args.mirror_path)
    inventory = build_cbl_inventory(parsed, failures)
    failed_paths = frozenset(failure.source_path for failure in failures)
    parse_failures = [asdict(failure) for failure in failures]
    repository_aliases = tuple(getattr(args, "reconcile_repository", ()))

    if getattr(args, "inventory_only", False):
        payload = {
            "mode": "inventory",
            "repository": args.repository,
            "revision_sha": args.revision_sha,
            "inventory": asdict(inventory),
            "parsed_lists": len(parsed),
            "parse_failures": parse_failures,
        }
        print(json.dumps(payload, sort_keys=True))
        return 1 if failures else 0

    async with AsyncSessionLocal() as db:
        async with db.begin():
            summary = await sync_cbl_lists(
                db,
                repository=args.repository,
                revision_sha=args.revision_sha,
                parsed_lists=parsed,
                protected_paths=failed_paths,
                repository_aliases=repository_aliases,
                dry_run=args.dry_run,
            )

    payload = {
        "mode": "dry_run" if args.dry_run else "sync",
        "repository": args.repository,
        "repository_aliases": list(repository_aliases),
        "revision_sha": args.revision_sha,
        "inventory": asdict(inventory),
        **asdict(summary),
        "parsed_lists": len(parsed),
        "parse_failures": parse_failures,
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
