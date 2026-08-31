#!/usr/bin/env python3
"""Rebuild one crossover's issue membership from a reconciled CBL source list.

This one-off, auditable repair carries authoritative CBL source order through
canonical reconciliation into a production crossover. It defaults to Ultimate
Universe crossover #15 for user 1, but all targets are explicit CLI arguments.

The command is dry-run by default. ``--commit`` is required to mutate data.
Existing issue read state and ``read_at`` values are never rewritten.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.services.cbl_reconciliation import reconcile_cbl_source_list

DEFAULT_GROUP_ID = 15
DEFAULT_USER_ID = 1


def _parser() -> argparse.ArgumentParser:
    """Build command-line arguments for the crossover rebuild utility."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-list-id",
        type=int,
        required=True,
        help="Normalized CBL source list id to reconcile from.",
    )
    parser.add_argument(
        "--group-id",
        type=int,
        default=DEFAULT_GROUP_ID,
        help=f"Dependency group id to rebuild (default: {DEFAULT_GROUP_ID}).",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=DEFAULT_USER_ID,
        help=f"Owner user id of the crossover (default: {DEFAULT_USER_ID}).",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Apply the rebuild. Without this flag the script only reports.",
    )
    return parser


def _entry_row(entry: dict[str, object]) -> dict[str, object]:
    """Serialize one reconciled entry for JSON output."""
    read_at = entry.get("read_at")
    if isinstance(read_at, str):
        iso: str | None = read_at
    else:
        iso = _iso(read_at) if isinstance(read_at, datetime) else None
    return {
        "cbl_position": entry.get("cbl_position"),
        "series_name": entry.get("series_name"),
        "issue_number": entry.get("issue_number"),
        "comicvine_issue_id": entry.get("comicvine_issue_id"),
        "resolved_issue_id": entry.get("resolved_issue_id"),
        "resolution_status": entry.get("resolution_status"),
        "read_status": entry.get("read_status"),
        "read_at": iso,
    }


def _iso(value: datetime | None) -> str | None:
    """Format a datetime as ISO-8601 string or ``None``."""
    return value.isoformat() if value is not None else None


async def _member_issue_ids(db: AsyncSession, group_id: int) -> list[int]:
    """Return current issue-level membership ids in stable order."""
    rows = (
        await db.execute(
            select(DependencyGroupMembership.issue_id).where(
                DependencyGroupMembership.group_id == group_id,
                DependencyGroupMembership.issue_id.isnot(None),
            )
        )
    ).scalars().all()
    return sorted(rows)


async def _memberships(
    db: AsyncSession, group_id: int
) -> list[DependencyGroupMembership]:
    """Return the crossover's issue-level membership rows."""
    rows = (
        await db.execute(
            select(DependencyGroupMembership).where(
                DependencyGroupMembership.group_id == group_id,
                DependencyGroupMembership.issue_id.isnot(None),
            )
        )
    ).scalars().all()
    return list(rows)


async def _all_memberships(
    db: AsyncSession, group_id: int
) -> list[DependencyGroupMembership]:
    """Return all membership rows for a crossover."""
    rows = (
        await db.execute(
            select(DependencyGroupMembership).where(
                DependencyGroupMembership.group_id == group_id
            )
        )
    ).scalars().all()
    return list(rows)


async def _group(
    db: AsyncSession, args: argparse.Namespace
) -> DependencyGroup | None:
    """Return the owned target dependency group, or ``None`` if absent."""
    result = await db.execute(
        select(DependencyGroup).where(
            DependencyGroup.id == args.group_id,
            DependencyGroup.user_id == args.user_id,
        )
    )
    return result.scalar_one_or_none()


async def _rebuild(
    db: AsyncSession,
    args: argparse.Namespace,
) -> dict[str, object]:
    """Reconcile the source list and optionally rebuild crossover membership."""
    current_ids = await _member_issue_ids(db, args.group_id)
    report = await reconcile_cbl_source_list(
        db,
        source_list_id=args.source_list_id,
        user_id=args.user_id,
        baseline_member_issue_ids=tuple(current_ids),
    )

    resolved_with_pos = sorted(
        (
            int(entry["cbl_position"]),
            int(entry["resolved_issue_id"]),
        )
        for entry in report.entries
        if entry.get("resolved_issue_id") is not None
    )
    resolved_ids = [issue_id for _position, issue_id in resolved_with_pos]
    resolved_id_set = set(resolved_ids)

    group = await _group(db, args)
    current_memberships = await _memberships(db, args.group_id)
    all_memberships = await _all_memberships(db, args.group_id)
    thread_memberships = [
        membership
        for membership in all_memberships
        if membership.thread_id is not None
    ]

    to_add = [issue_id for issue_id in resolved_ids if issue_id not in current_ids]
    to_remove = [
        membership
        for membership in current_memberships
        if membership.issue_id not in resolved_id_set
    ]

    dry_run = not args.commit
    if not dry_run:
        for membership in current_memberships:
            await db.delete(membership)
        for membership in thread_memberships:
            await db.delete(membership)
        await db.flush()
        for position, issue_id in resolved_with_pos:
            db.add(
                DependencyGroupMembership(
                    group_id=args.group_id,
                    issue_id=issue_id,
                    sequence_order=position,
                )
            )
        await db.commit()

    return {
        "source_list_id": report.source_list_id,
        "source_repository": report.source_repository,
        "source_path": report.source_path,
        "declared_issue_count": report.declared_issue_count,
        "dry_run": dry_run,
        "group_id": args.group_id,
        "user_id": args.user_id,
        "group_name": group.name if group is not None else None,
        "entries_total": len(report.entries),
        "entries_resolved": len(resolved_with_pos),
        "members_for_group_before": current_ids,
        "members_to_add": sorted(to_add),
        "members_removed_extra": sorted(
            membership.issue_id for membership in to_remove
        ),
        "missing_source_entries": list(report.missing_source_entries),
        "ambiguous_mappings": list(report.ambiguous_mappings),
        "duplicate_identity_issues": list(report.duplicate_identity_issues),
        "extra_member_issue_ids": list(report.extra_member_issue_ids),
        "first_unread_position": report.first_unread_position,
        "first_unread_issue_id": report.first_unread_issue_id,
        "entries": [_entry_row(entry) for entry in report.entries],
    }


def main() -> int:
    """Run the crossover rebuild command and print the JSON verification report."""
    args = _parser().parse_args()

    async def _run() -> dict[str, object]:
        async with AsyncSessionLocal() as db:
            return await _rebuild(db, args)

    try:
        payload = asyncio.run(_run())
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
