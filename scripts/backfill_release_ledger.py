#!/usr/bin/env python3
"""Audit, import, and reconcile the historical ComicPile changelog release ledger."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

# Running a script by path puts scripts/ rather than the repository root on
# sys.path. Add the checkout root before importing the application package so
# the documented one-shot command works in CI and from a clean checkout.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser with dry-run as the safe default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist validated candidates after printing the complete dry-run audit.",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="ComicPile checkout root containing docs/changelog.md and docs/changelog.d.",
    )
    return parser


async def _run(repository_root: Path, *, write: bool) -> int:
    """Execute one dry-run or write/reconciliation pass."""
    from app.database import AsyncSessionLocal
    from app.services.release_import import (
        audit_changelog_corpus,
        import_changelog_report,
        reconcile_changelog_report,
    )

    audit = audit_changelog_corpus(repository_root)
    print(json.dumps({"phase": "audit", **audit.as_dict()}, indent=2, sort_keys=True))
    if not write:
        return 0

    async with AsyncSessionLocal() as db:
        write_report = await import_changelog_report(db, audit)
        print(
            json.dumps(
                {"phase": "write", **write_report.as_dict()},
                indent=2,
                sort_keys=True,
            )
        )
        verification = await reconcile_changelog_report(db, audit)
        print(
            json.dumps(
                {"phase": "reconciliation", **verification.as_dict()},
                indent=2,
                sort_keys=True,
            )
        )

    if write_report.conflicts:
        return 2
    if verification.conflicts or verification.missing_count:
        return 3
    return 0


def main() -> int:
    """Run the backfill command and return a machine-friendly exit status."""
    args = _parser().parse_args()
    return asyncio.run(_run(args.repository_root.resolve(), write=args.write))


if __name__ == "__main__":
    raise SystemExit(main())
