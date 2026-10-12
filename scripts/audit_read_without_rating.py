#!/usr/bin/env python3
"""Audit (and deterministically repair) read-without-rating issues (#3175).

This script is the repeatable audit/repair command for the creator-comparison
"read with no stored rating" population.

- Default (audit) mode is read-only. It counts the population, breaks it down
  by evidenced cause, thread, and creator, and lists every unresolved row with
  the identity evidence needed to inspect it. Exits 0 when clean, 1 when
  unresolved rows remain.
- ``--apply`` runs the idempotent safe repair: it inserts one issue-linked
  ``rate`` event only for rows whose cause is ``missing_rate_event``, i.e. a
  single agreed thread-level historical rating against a thread holding exactly
  one unrated read issue. Every other cause is left untouched, so ambiguous
  identity and unresolved mappings are never guessed. Reruns insert nothing.

No rating is ever inferred from averages, neighboring issues, or creator
statistics. This tool never touches production unless explicitly pointed at it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Register every mapper before any query. ``app.models`` does not re-export
# ``PasswordResetToken``, so ``User.password_reset_tokens`` cannot resolve
# without importing that module explicitly.
import app.models  # noqa: F401,E402
from app.models import password_reset_token as _password_reset_token  # noqa: F401,E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.services.read_without_rating_audit import (  # noqa: E402
    CAUSE_MISSING_RATE_EVENT,
    audit_read_without_rating,
    repair_safe_missing_ratings,
)

DEFAULT_USER_ID = 1


async def audit(db: AsyncSession, user_id: int) -> dict[str, Any]:
    """Return a read-only read-without-rating report for one user."""
    result = await audit_read_without_rating(db, user_id)
    return {
        "user_id": result.user_id,
        "total": result.total,
        "by_cause": result.by_cause,
        "effective_rated_issues": result.effective_rated_issues,
        "by_thread": [
            {
                "thread_id": thread_id,
                "thread_title": summary.thread_title,
                "total": summary.total,
                "by_cause": summary.by_cause,
            }
            for thread_id, summary in sorted(
                result.by_thread.items(), key=lambda item: (-item[1].total, item[0])
            )
        ],
        "creator_impact": [
            {
                "display_name": summary.display_name,
                "total": summary.total,
                "by_cause": summary.by_cause,
            }
            for summary in result.creator_impact
        ],
        "issues": [
            {
                "issue_id": row.issue_id,
                "issue_number": row.issue_number,
                "thread_id": row.thread_id,
                "thread_title": row.thread_title,
                "cause": row.cause.cause,
                "repair_safe": row.cause.repair_safe,
                "missing_evidence": row.cause.missing_evidence,
                "source_rating": row.cause.source_rating,
                "detail": row.cause.detail,
            }
            for row in result.issues
        ],
    }


async def repair(db: AsyncSession, user_id: int) -> dict[str, Any]:
    """Run the idempotent safe repair and report what actually changed."""
    report = await repair_safe_missing_ratings(db, user_id)
    unresolved = report.skipped_by_cause.get(CAUSE_MISSING_RATE_EVENT, 0)
    return {
        "user_id": report.user_id,
        "effective_before": report.effective_before,
        "effective_after": report.effective_after,
        "repaired": report.repaired,
        "repaired_cause": CAUSE_MISSING_RATE_EVENT,
        "repaired_issue_ids": report.repaired_issue_ids,
        "skipped_by_cause": report.skipped_by_cause,
        "repair_safe_rows_left_unrepaired": unresolved,
    }


async def main_async(args: argparse.Namespace) -> int:
    """Run the audit or repair and return the process exit code."""
    async with AsyncSessionLocal() as db:
        if args.apply:
            result = await repair(db, args.user_id)
            print(json.dumps(result, indent=2, default=str))
            # Unresolved rows remain after a safe repair by design; they are
            # reported, never forced. Only a vanished user id is a failure.
            return 0
        report = await audit(db, args.user_id)
        print(json.dumps(report, indent=2, default=str))
        return 1 if report["total"] else 0


def main() -> int:
    """Parse arguments and run the audit or repair."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Repair safely matchable rows (default: read-only audit).",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=DEFAULT_USER_ID,
        help=f"Library owner to audit (default: {DEFAULT_USER_ID}).",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())