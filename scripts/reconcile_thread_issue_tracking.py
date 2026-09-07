"""Repair thread issue-tracking counters that drifted from local issue rows.

Threads materialized from a partially adopted external series could publish
the external volume size as ``total_issues``/``issues_remaining`` while owning
only the adopted issue rows. This pass re-derives those counters, plus
``next_unread_issue_id`` and ``reading_progress``, from the rows each thread
actually owns.

The pass never mutates read history (issue status, read timestamps, ratings),
never creates or deletes issue rows, and never changes thread lifecycle status.
It is a dry run unless ``--commit`` is passed.

Requires the standard application database configuration (DATABASE_URL or
TEST_DATABASE_URL).

Example:
    uv run python scripts/reconcile_thread_issue_tracking.py --limit 100
    uv run python scripts/reconcile_thread_issue_tracking.py --commit
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json

from app.database import AsyncSessionLocal
from app.services.thread_issue_tracking_reconciliation import (
    ThreadIssueTrackingReconciliationReport,
    reconcile_thread_issue_tracking,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list to parse; defaults to sys.argv[1:].

    Returns:
        Parsed CLI arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Re-derive thread issue-tracking counters from locally adopted issue rows."
        )
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Restrict the pass to one thread owner.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of drifted threads to inspect in this bounded pass.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Persist the repairs instead of running a dry pass.",
    )
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> ThreadIssueTrackingReconciliationReport:
    """Execute one bounded issue-tracking reconciliation pass.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Report describing inspected and repaired threads.
    """
    async with AsyncSessionLocal() as db:
        return await reconcile_thread_issue_tracking(
            db, user_id=args.user_id, limit=args.limit, commit=args.commit
        )


def main() -> None:
    """Run the reconciliation command and print the JSON report."""
    report = asyncio.run(run(parse_args()))
    print(json.dumps(dataclasses.asdict(report), sort_keys=True))


if __name__ == "__main__":
    main()
