#!/usr/bin/env python3
"""Persist canonical Dependency edges from rule-native ContinuityRule rows.

This script implements Step 1 of the runtime cutover (issue #2553):
- Convert rule-native `item_read` ContinuityRule rows (807) to Dependency edges
- Convert `converged` ContinuityRule rows (130 rules, 135 edges) to multiple incoming Dependency edges
- Preserve provenance through the `note` field (e.g., `continuity-plan:<plan_id>`)

Only rule-native rules (those without a `legacy_dependency_id`) are converted.
Rules that already have a mirroring Dependency row are skipped (2,380 mirrored rules).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_application_symbols():
    from app.database import AsyncSessionLocal
    from app.models.continuity_rule import ContinuityRule
    from app.models.dependency import Dependency
    from app.models.thread import Thread
    from app.models.issue import Issue


    return AsyncSessionLocal, ContinuityRule, Dependency, Issue, Thread


AsyncSessionLocal, ContinuityRule, Dependency, Issue, Thread = _load_application_symbols()


CONFIRMATION = "PERSIST-CANONICAL-DEPENDENCIES"


async def _dry_run(db: AsyncSession) -> dict:
    """Analyze rule-native ContinuityRule rows and compute the Dependency edges to persist."""
    from sqlalchemy import select

    # Load all rule-native ContinuityRule rows (no legacy_dependency_id)
    result = await db.execute(
        select(ContinuityRule)
        .where(ContinuityRule.legacy_dependency_id.is_(None))
        .where(ContinuityRule.target_type == "issue")
        .where(ContinuityRule.source_type == "issue")
        .order_by(ContinuityRule.id)
    )
    rule_native_rules = list(result.scalars().all())

    # Load all existing Dependency edges for quick lookup
    result = await db.execute(select(Dependency.source_issue_id, Dependency.target_issue_id))
    existing_edges = {(row[0], row[1]) for row in result.all()}

    # Load issues to verify ownership and existence
    result = await db.execute(select(Issue.id, Issue.thread_id))
    issue_threads = {row[0]: row[1] for row in result.all()}

    # Load threads to verify user ownership
    result = await db.execute(select(Thread.id, Thread.user_id))
    thread_users = {row[0]: row[1] for row in result.all()}


    edges_to_create: list[dict] = []
    skipped_mirrored: list[dict] = []
    skipped_invalid: list[dict] = []

    for rule in rule_native_rules:
        source_id = rule.source_id
        target_id = rule.target_id

        # Verify both issues exist and belong to the same user
        source_thread_id = issue_threads.get(source_id)
        target_thread_id = issue_threads.get(target_id)

        if source_thread_id is None or target_thread_id is None:
            skipped_invalid.append(
                {
                    "rule_id": rule.id,
                    "reason": "source or target issue not found",
                    "source_id": source_id,
                    "target_id": target_id,
                }
            )
            continue

        source_user_id = thread_users.get(source_thread_id)
        target_user_id = thread_users.get(target_thread_id)

        if source_user_id != target_user_id or source_user_id != rule.user_id:
            skipped_invalid.append(
                {
                    "rule_id": rule.id,
                    "reason": "ownership mismatch",
                    "source_user_id": source_user_id,
                    "target_user_id": target_user_id,
                    "rule_user_id": rule.user_id,
                }
            )
            continue

        if rule.satisfaction_type == "item_read":
            edge_key = (source_id, target_id)
            if edge_key in existing_edges:
                skipped_mirrored.append(
                    {
                        "rule_id": rule.id,
                        "source_issue_id": source_id,
                        "target_issue_id": target_id,
                        "note": rule.note,
                    }
                )
            else:
                edges_to_create.append(
                    {
                        "source_issue_id": source_id,
                        "target_issue_id": target_id,
                        "note": rule.note,
                        "source_rule_id": rule.id,
                    }
                )
        elif rule.satisfaction_type == "converged":
            if rule.convergence_targets:
                for target_info in rule.convergence_targets:
                    if target_info.get("type") == "issue":
                        prereq_id = target_info["id"]
                        edge_key = (prereq_id, target_id)
                        if edge_key in existing_edges:
                            skipped_mirrored.append(
                                {
                                    "rule_id": rule.id,
                                    "source_issue_id": prereq_id,
                                    "target_issue_id": target_id,
                                    "note": rule.note,
                                }
                            )
                        else:
                            # Verify prereq issue exists and belongs to same user
                            prereq_thread_id = issue_threads.get(prereq_id)
                            if prereq_thread_id is None:
                                skipped_invalid.append(
                                    {
                                        "rule_id": rule.id,
                                        "reason": "convergence prerequisite issue not found",
                                        "prereq_id": prereq_id,
                                    }
                                )
                                continue
                            prereq_user_id = thread_users.get(prereq_thread_id)
                            if prereq_user_id != rule.user_id:
                                skipped_invalid.append(
                                    {
                                        "rule_id": rule.id,
                                        "reason": "convergence prerequisite ownership mismatch",
                                        "prereq_user_id": prereq_user_id,
                                        "rule_user_id": rule.user_id,
                                    }
                                )
                                continue
                            edges_to_create.append(
                                {
                                    "source_issue_id": prereq_id,
                                    "target_issue_id": target_id,
                                    "note": rule.note,
                                    "source_rule_id": rule.id,
                                }
                            )

    return {
        "rule_native_count": len(rule_native_rules),
        "edges_to_create": edges_to_create,
        "skipped_mirrored_count": len(skipped_mirrored),
        "skipped_invalid_count": len(skipped_invalid),
        "skipped_mirrored": skipped_mirrored,
        "skipped_invalid": skipped_invalid,
    }


async def _apply(db: AsyncSession, dry_run_report: dict) -> dict:
    """Persist the computed Dependency edges."""
    edges_to_create = dry_run_report["edges_to_create"]
    created_edges: list[dict] = []

    for edge_data in edges_to_create:
        dep = Dependency(
            source_issue_id=edge_data["source_issue_id"],
            target_issue_id=edge_data["target_issue_id"],
            note=edge_data["note"],
        )
        db.add(dep)
        await db.flush()
        created_edges.append(
            {
                "dependency_id": dep.id,
                "source_issue_id": edge_data["source_issue_id"],
                "target_issue_id": edge_data["target_issue_id"],
                "note": edge_data["note"],
                "source_rule_id": edge_data["source_rule_id"],
            }
        )

    return {
        "created_count": len(created_edges),
        "created_edges": created_edges,
    }


async def _verify_canonical_set(db: AsyncSession) -> dict:
    """Verify the canonical Dependency set matches expectations."""
    from sqlalchemy import select

    # Count canonical edges: note IS NULL OR note NOT LIKE 'cbl-order:%'
    result = await db.execute(
        select(Dependency).where(
            (Dependency.note.is_(None)) | (~Dependency.note.like("cbl-order:%"))
        )
    )
    canonical_deps = list(result.scalars().all())

    # Count by note type
    note_counts: dict[str, int] = {}
    for dep in canonical_deps:
        note_key = dep.note or "(null)"
        note_counts[note_key] = note_counts.get(note_key, 0) + 1

    return {
        "canonical_dependency_count": len(canonical_deps),
        "note_distribution": note_counts,
    }


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Persist canonical Dependency edges from ContinuityRule")
    parser.add_argument("--dry-run", action="store_true", help="Analyze without persisting")
    parser.add_argument("--output", type=Path, help="Output JSON path for dry-run report")
    parser.add_argument("--apply", action="store_true", help="Apply the migration")
    parser.add_argument("--snapshot", type=Path, help="Dry-run snapshot to apply")
    parser.add_argument("--receipt", type=Path, help="Receipt output path for apply")
    parser.add_argument("--confirm", help="Confirmation token for apply")
    parser.add_argument("--verify", action="store_true", help="Verify canonical set after apply")

    args = parser.parse_args()

    if args.apply and args.confirm != CONFIRMATION:
        print(f"Apply requires --confirm {CONFIRMATION}", file=sys.stderr)
        return 2

    async with AsyncSessionLocal() as db:
        try:
            if args.dry_run:
                report = await _dry_run(db)
                if args.output:
                    import json as _json
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(_json.dumps(report, indent=2, sort_keys=True) + "\n")
                print(json.dumps(report, indent=2, sort_keys=True))
                await db.rollback()
                return 0

            if args.apply:
                if not args.snapshot or not args.receipt:
                    print("--apply requires --snapshot and --receipt", file=sys.stderr)
                    return 2
                import json as _json
                snapshot = _json.loads(args.snapshot.read_text())
                result = await _apply(db, snapshot)
                await db.commit()
                receipt = {"source_snapshot": str(args.snapshot), **result}
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                args.receipt.write_text(_json.dumps(receipt, indent=2, sort_keys=True) + "\n")
                print(json.dumps(receipt, indent=2, sort_keys=True))
                return 0

            if args.verify:
                report = await _verify_canonical_set(db)
                print(json.dumps(report, indent=2, sort_keys=True))
                await db.rollback()
                return 0

            print("Specify --dry-run, --apply, or --verify", file=sys.stderr)
            return 2
        except Exception:
            await db.rollback()
            raise


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main()))
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc