#!/usr/bin/env python3
"""Repeatable audit/report and reconciliation command for Reading Plan duplicates.

Reading Plan membership is set membership: one canonical Issue belongs to a plan
at most once (``uq_reading_plan_issue_plan_issue``). This command reports every
plan that still violates that invariant and can deterministically collapse it.

Read-only by default. ``--reconcile`` mutates the database, so it requires a
provably local database target and leaves the transaction to the caller unless
``--commit`` is passed.

Exit codes:
    0  every audited plan satisfies the invariant
    1  duplicate memberships found (reconciled when ``--reconcile`` is used)
    2  duplicates found but left alone because they conflict and
       ``--allow-conflicts`` was not passed
    3  the command could not complete

Examples::

    python scripts/audit_reading_plan_duplicate_memberships.py
    python scripts/audit_reading_plan_duplicate_memberships.py --plan-id 12 --json
    python scripts/audit_reading_plan_duplicate_memberships.py --reconcile --commit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.exc import SQLAlchemyError

from app.database import AsyncSessionLocal
from app.services.reading_plan_audit import (
    PlanAuditResult,
    audit_reading_plan_duplicate_memberships,
    create_reconciliation_plan,
    reconcile_reading_plan_duplicate_memberships,
)
from scripts.database_target_safety import require_local_database_url

EXIT_CLEAN = 0
EXIT_DUPLICATES = 1
EXIT_BLOCKED = 2
EXIT_ERROR = 3


def _report_payload(result: PlanAuditResult) -> list[dict[str, object]]:
    """Render the audit result as deterministic JSON-ready rows."""
    payload: list[dict[str, object]] = []
    for report in result.reports:
        plan = create_reconciliation_plan(report)
        payload.append(
            {
                "plan_id": report.plan_id,
                "duplicate_issues": report.total_duplicate_issues,
                "extra_occurrences": report.total_extra_occurrences,
                "conflicting_issue_ids": list(report.conflicting_issue_ids),
                "reconciliation": {
                    "survivor_by_issue": {
                        str(issue_id): occurrence_id
                        for issue_id, occurrence_id in sorted(
                            plan.primary_occurrence_ids.items()
                        )
                    },
                    "removed_occurrences": sorted(plan.removal_occurrence_ids),
                },
                "duplicates": [
                    {
                        "issue_id": duplicate.issue_id,
                        "occurrence_ids": list(duplicate.occurrence_ids),
                        "display_positions": list(duplicate.display_positions),
                        "lane_ids": list(duplicate.lane_ids),
                        "conflicting_fields": list(duplicate.conflicting_fields),
                    }
                    for duplicate in report.duplicates
                ],
            }
        )
    return payload


def _print_report(result: PlanAuditResult, *, as_json: bool) -> None:
    """Print the audit result in the requested format."""
    payload = _report_payload(result)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if not payload:
        print("reading-plan membership audit: no duplicate memberships found")
        return
    print(
        "reading-plan membership audit: "
        f"{result.total_duplicate_issues} duplicate issue(s) across "
        f"{len(payload)} plan(s), {result.total_extra_occurrences} extra occurrence(s)"
    )
    for plan in payload:
        reconciliation = plan["reconciliation"]
        print(f"  plan {plan['plan_id']}:")
        for duplicate in plan["duplicates"]:
            conflicts = duplicate["conflicting_fields"]
            suffix = f" conflicting fields: {', '.join(conflicts)}" if conflicts else ""
            print(
                f"    issue {duplicate['issue_id']} occurs "
                f"{len(duplicate['occurrence_ids'])}x as "
                f"{duplicate['occurrence_ids']}{suffix}"
            )
        print(f"    survivors: {reconciliation['survivor_by_issue']}")
        print(f"    removed:   {reconciliation['removed_occurrences']}")


async def run(args: argparse.Namespace) -> int:
    """Run the audit, optionally reconcile, and return the process exit code."""
    if args.reconcile:
        require_local_database_url(os.getenv("DATABASE_URL", ""))

    async with AsyncSessionLocal() as db:
        if args.reconcile:
            result = await reconcile_reading_plan_duplicate_memberships(
                db,
                plan_id=args.plan_id,
                allow_conflicts=args.allow_conflicts,
            )
            if args.commit:
                await db.commit()
            else:
                await db.rollback()
        else:
            result = await audit_reading_plan_duplicate_memberships(
                db, plan_id=args.plan_id
            )

    _print_report(result, as_json=args.json)
    if result.is_clean:
        return EXIT_CLEAN
    blocked = any(
        create_reconciliation_plan(report).has_conflicts for report in result.reports
    )
    if args.reconcile and blocked and not args.allow_conflicts:
        print(
            "conflicting duplicates were left unchanged; "
            "review them or re-run with --allow-conflicts"
        )
        return EXIT_BLOCKED
    return EXIT_DUPLICATES


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan-id",
        type=int,
        default=None,
        help="Audit only one plan ID instead of every plan with membership rows.",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Collapse duplicates deterministically. Requires a local database.",
    )
    parser.add_argument(
        "--allow-conflicts",
        action="store_true",
        help="Collapse even when duplicate occurrences disagree on reader-visible state.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Commit a reconciliation. Without this flag the transaction rolls back.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args(argv)

    if args.commit and not args.reconcile:
        parser.error("--commit requires --reconcile")
    if args.allow_conflicts and not args.reconcile:
        parser.error("--allow-conflicts requires --reconcile")

    try:
        return asyncio.run(run(args))
    except SQLAlchemyError as error:
        print(f"reading-plan membership audit failed: {error}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())