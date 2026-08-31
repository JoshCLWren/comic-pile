"""Standalone diagnostic script for crossover readiness.

Run via GitHub Actions workflow_dispatch with bounded inputs:
  --mode        diagnostic mode (currently: "crossover-readiness")
  --group_id    crossover group ID to investigate
  --user_id     owning user ID (defaults to 1 for automated diagnostics)

Outputs human-readable diagnostics about why a crossover may have unread
blockers. Read-only: never modifies production data, never prints credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_database_settings
from app.services.continuity_graph import (
    GROUP_ISSUE_IDS_SUMMARY,
    GraphSnapshot,
    crossover_readiness,
    group_issue_ids,
    load_snapshot,
)
from app.safe_logging import safe_exception_metadata

logger = logging.getLogger(__name__)

ASYNC_DATABASE_URL: str = get_database_settings().async_url

AsyncSessionLocal = async_sessionmaker(
    create_async_engine(
        ASYNC_DATABASE_URL,
        pool_size=2,
        max_overflow=0,
        pool_timeout=10.0,
        pool_pre_ping=True,
        connect_args={"timeout": 10.0, "command_timeout": 8.0},
    ),
    autocommit=False,
    autoflush=True,
    expire_on_commit=False,
)


async def _acquire_session() -> AsyncSession:
    """Acquire an async database session."""
    session: AsyncSession | None = None
    try:
        session = AsyncSessionLocal()
        await session.connection()
        return session
    except Exception as error:
        logger.error("Failed to acquire database session: %s", safe_exception_metadata(error))
        raise


async def _run_diagnostic(mode: str, group_id: int, user_id: int) -> dict:
    """Execute the requested diagnostic mode and return structured results."""
    if mode != "crossover-readiness":
        msg = f"Unsupported diagnostic mode: {mode}"
        logger.error(msg)
        raise ValueError(msg)

    async with _acquire_session() as db:
        try:
            snapshot: GraphSnapshot = await load_snapshot(db, user_id)
        except Exception as error:
            logger.error("Failed to load snapshot: %s", safe_exception_metadata(error))
            raise

    blockers = crossover_readiness(group_id, snapshot)

    # Build human-readable summary
    issue_ids = group_issue_ids(group_id, snapshot)
    group = snapshot.groups.get(group_id)

    result: dict = {
        "mode": mode,
        "group_id": group_id,
        "group_name": group.name if group else f"Crossover {group_id}",
        "user_id": user_id,
        "total_issues_in_group": len(issue_ids),
        "blocker_count": len(blockers),
        "blockers": [],
    }

    for blocker in blockers:
        blocker_entry: dict = {
            "rule_id": blocker.rule_id,
            "satisfaction_type": blocker.satisfaction_type,
            "blocker_type": blocker.blocker_type,
            "source_type": blocker.source_type,
            "source_id": blocker.source_id,
            "source_label": blocker.source_label,
            "causing_issue_ids": blocker.causing_issue_ids,
            "causing_member_issue_ids": blocker.causing_member_issue_ids,
            "unread_issue_details": [
                {"issue_id": detail.issue_id, "label": detail.label}
                for detail in blocker.unread_issue_details
            ],
            "note": blocker.note,
        }
        result["blockers"].append(blocker_entry)

    # Add summary of unread issues
    unread_issues: list[dict] = []
    for issue_id in issue_ids:
        if not is_read(issue_id, snapshot):
            thread = snapshot.threads.get(snapshot.issues[issue_id].thread_id) if issue_id in [
                issue.id for issue in snapshot.issues.values()
            ] else None
            thread_title = thread.title if thread else "unknown"
            issue_num = snapshot.issues[issue_id].issue_number if issue_id in {
                issue.id for issue in snapshot.issues.values()
            } else None
            unread_issues.append(
                {
                    "issue_id": issue_id,
                    "issue_number": issue_num,
                    "thread_title": thread_title,
                    "label": f"{thread_title} #{issue_num}" if thread_title != "unknown" else f"Issue {issue_id}",
                }
            )

    result["unread_issues"] = unread_issues

    return result


def _main(argv: list[str] | None = None) -> int:
    """Entry point for the diagnostic script."""
    parser = argparse.ArgumentParser(
        description="Crossover readiness diagnostic (read-only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["crossover-readiness"],
        help="Diagnostic mode to run",
    )
    parser.add_argument(
        "--group_id",
        required=True,
        type=int,
        help="Crossover group ID to investigate",
    )
    parser.add_argument(
        "--user_id",
        type=int,
        default=1,
        help="Owning user ID for the continuity graph (default: 1)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of human-readable text",
    )
    args = parser.parse_args(argv)

    try:
        result = asyncio.run(_run_diagnostic(args.mode, args.group_id, args.user_id))

        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            group_name = result["group_name"]
            group_id = result["group_id"]
            user_id = result["user_id"]
            total_issues = result["total_issues_in_group"]
            blocker_count = result["blocker_count"]

            print(f"=== Crossover Readiness Diagnostic ===")
            print(f"Group: {group_name} (ID: {group_id})")
            print(f"User ID: {user_id}")
            print(f"Total issues in group: {total_issues}")
            print(f"Blockers: {blocker_count}")
            print()

            if blocker_count > 0:
                print("Blockers:")
                for blocker in result["blockers"]:
                    note = blocker.get("note", "No note available")
                    causing = blocker.get("causing_issue_ids", [])
                    causing_members = blocker.get("causing_member_issue_ids", [])
                    source_label = blocker.get("source_label", "unknown source")
                    sat_type = blocker.get("satisfaction_type", "unknown")
                    btype = blocker.get("blocker_type", "unknown")

                    print(f"  - Rule ID: {blocker.get('rule_id', 'N/A')}")
                    print(f"    Satisfaction type: {sat_type}")
                    print(f"    Blocker type: {btype}")
                    print(f"    Source: {source_label}")
                    if causing:
                        print(f"    Causing unread issues: {causing}")
                    if causing_members:
                        print(f"    Causing unread members: {causing_members}")
                    print()
            else:
                print("No blockers found. The crossover is fully readable.")

            if result["unread_issues"]:
                print(f"\nUnread issues ({len(result['unread_issues'])}):")
                for issue in result["unread_issues"]:
                    print(f"  - Issue {issue['issue_id']}: {issue['label']}")

        return 0

    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Diagnostic failed: {error}", file=sys.stderr)
        logger.error("Diagnostic failed", extra={"error": safe_exception_metadata(error)})
        return 1


if __name__ == "__main__":
    sys.exit(_main())


def _make_parser_help() -> str:
    """Return the parser help text (for documentation generation)."""
    parser = argparse.ArgumentParser(
        description="Crossover readiness diagnostic (read-only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", required=True, choices=["crossover-readiness"], help="Diagnostic mode")
    parser.add_argument("--group_id", required=True, type=int, help="Crossover group ID")
    parser.add_argument("--user_id", type=int, default=1, help="Owning user ID")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    return parser.format_help()