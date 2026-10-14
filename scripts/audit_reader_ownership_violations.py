#!/usr/bin/env python3
"""Audit existing reader-ownership violations at graph and library write edges (#3225).

This script is the repeatable, read-only report that must be run *before*
migration ``m5d400000001`` introduces the reader-ownership triggers. The
machine-enforced production gate is ``alembic/preflight/m5d400000001.json``;
this command exists so the same evidence can be produced on demand and attached
to a change, a migration review, or an incident.

What it reports:

- ``thread_frontier_outside_thread`` - a thread whose ``next_unread_issue_id``
  points at an issue of a different thread. Both threads may belong to the same
  reader; the frontier is still invalid.
- ``session_pending_thread_other_reader`` - a reading session whose
  ``pending_thread_id`` points at another reader's thread.

The report is deliberately payload-free: every section returns a count plus a
bounded list of primary keys, never titles, notes, ratings, corrections, tags,
events, or any other reader content, so it is safe to attach to a change.

The command is read-only by design. It never deletes, remaps, or auto-repairs a
row: ambiguous ownership stays a human decision. Exits 0 when clean and 1 when
any violation exists.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import AsyncSessionLocal
from app.services.ownership_consistency import (
    REPORT_ROW_LIMIT,
    reader_ownership_violation_report,
)


async def audit(*, limit: int = REPORT_ROW_LIMIT) -> dict[str, Any]:
    """Return a read-only reader-ownership violation report.

    Args:
        limit: Maximum number of identifying rows returned per section.

    Returns:
        Mapping of violation class to ``{"count": int, "rows": [...]}``. No
        reader content is selected.
    """
    async with AsyncSessionLocal() as db:
        return await reader_ownership_violation_report(db, limit=limit)


async def main_async(args: argparse.Namespace) -> int:
    """Run the read-only audit and return the process exit code.

    Args:
        args: Parsed command-line arguments.

    Returns:
        ``1`` when any violation exists, ``0`` otherwise.
    """
    report = await audit(limit=args.limit)
    print(json.dumps(report, indent=2, default=str))
    violations = sum(int(section["count"]) for section in report.values())
    if violations:
        print(
            f"reader-ownership violations found: {violations}; "
            "resolve them before enabling the constraints",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    """Parse arguments and run the read-only audit.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=REPORT_ROW_LIMIT,
        help=f"Maximum identifying rows per section (default: {REPORT_ROW_LIMIT}).",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())