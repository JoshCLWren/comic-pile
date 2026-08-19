#!/usr/bin/env python3
"""Synchronize a local CBL mirror into normalized ComicPile reference tables."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys

from sqlalchemy import select

from app.cbl_ingest import parse_cbl_mirror
from app.cbl_sync import sync_cbl_lists
from app.database import AsyncSessionLocal
from app.models.cbl_reference import CBLSource

DEFAULT_REPOSITORY = "JoshCLWren/CBL-ReadingLists"


def _parser() -> argparse.ArgumentParser:
    """Build command-line arguments for the CBL synchronization utility."""
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
        "--force",
        action="store_true",
        help="Reparse and reconcile even when this revision is already recorded",
    )
    return parser


async def _stored_revision(repository: str) -> str | None:
    """Return the last successfully synchronized revision for a source repository.

    Args:
        repository: Stable CBL source repository identity.

    Returns:
        The stored revision SHA, or ``None`` when this source has never synchronized.
    """
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CBLSource.revision_sha).where(CBLSource.repository == repository)
        )


async def _run(args: argparse.Namespace) -> int:
    """Reconcile the mirror when its source revision has changed.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process exit status. Zero means the mirror was synchronized or was already current.
    """
    repository = args.repository.strip()
    revision_sha = args.revision_sha.strip()
    if not repository:
        raise ValueError("repository is required")
    if not revision_sha:
        raise ValueError("revision_sha is required")

    if not args.force and not args.dry_run:
        stored_revision = await _stored_revision(repository)
        if stored_revision == revision_sha:
            print(
                json.dumps(
                    {
                        "repository": repository,
                        "revision_sha": revision_sha,
                        "skipped": True,
                        "reason": "revision_already_synchronized",
                    },
                    sort_keys=True,
                )
            )
            return 0

    parsed, failures = parse_cbl_mirror(args.mirror_path)
    failed_paths = frozenset(failure.source_path for failure in failures)
    async with AsyncSessionLocal() as db:
        async with db.begin():
            summary = await sync_cbl_lists(
                db,
                repository=repository,
                revision_sha=revision_sha,
                parsed_lists=parsed,
                protected_paths=failed_paths,
                dry_run=args.dry_run,
            )

    payload = {
        **asdict(summary),
        "repository": repository,
        "revision_sha": revision_sha,
        "skipped": False,
        "parsed_lists": len(parsed),
        "parse_failures": [asdict(failure) for failure in failures],
    }
    print(json.dumps(payload, sort_keys=True))
    return 1 if failures else 0


def main() -> int:
    """Run the asynchronous CBL mirror synchronization command."""
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
