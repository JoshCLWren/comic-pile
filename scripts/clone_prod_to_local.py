#!/usr/bin/env python3
"""Backup production user data and restore it into local dev.

Exports the authenticated user's data (threads, issues, sessions, etc.)
from a production PostgreSQL database into a structured JSON file, then
restores it into the local development database with ID remapping.

Never mutates production data. Never exports password hashes or auth tokens.

Usage:
    # Default: auto-fetches from Railway:
    python -m scripts.clone_prod_to_local export --username Josh

    # Override with a direct DB URL:
    python -m scripts.clone_prod_to_local export --db-url postgresql+asyncpg://...

    # Restore into local dev:
    python -m scripts.clone_prod_to_local import --file prod_export.json

Environment Variables:
    CLONE_PROD_DB_URL: Production DB URL (alternative to --db-url)
    COMIC_PILE_USERNAME: Production username (alternative to --username)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    Collection,
    Dependency,
    Event,
    Issue,
    ReadingOrder,
    ReadingOrderItem,
    Review,
    Session,
    Snapshot,
    Thread,
    User,
)


SCHEMA_VERSION = "1.0"

EXPORT_TABLES = [
    "user",
    "collections",
    "threads",
    "issues",
    "dependencies",
    "reading_orders",
    "reading_order_items",
    "sessions",
    "events",
    "snapshots",
    "reviews",
]



class _DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects."""

    def default(self, obj: object) -> object:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _fetch_railway_db_url() -> str:
    """Get the production database public URL from Railway CLI.

    Uses --service Postgres --environment production to get the
    DATABASE_PUBLIC_URL, which is reachable from outside Railway.

    Returns:
        The DATABASE_PUBLIC_URL from the Postgres service.

    Raises:
        SystemExit: If Railway CLI is not found, the command fails,
            or the variable is missing.
    """
    try:
        result = subprocess.run(
            [
                "railway", "variables",
                "--service", "Postgres",
                "--environment", "production",
                "--json",
            ],
            capture_output=True, text=True, check=True,
        )
        vars_data = json.loads(result.stdout)
        db_url = vars_data.get("DATABASE_PUBLIC_URL") or vars_data.get("DATABASE_URL")
        if not db_url:
            print("Error: DATABASE_PUBLIC_URL not found in Railway Postgres variables.", file=sys.stderr)
            sys.exit(1)
        return db_url
    except FileNotFoundError:
        print("Error: railway CLI not found in PATH.", file=sys.stderr)
        print("Install it from https://docs.railway.app/develop/cli", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error: railway variables failed: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: failed to parse Railway output: {e}", file=sys.stderr)
        sys.exit(1)


def _datetime_to_iso(obj: object) -> str | None:
    if isinstance(obj, datetime):
        return obj.isoformat()
    return None



def _export_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "created_at": _datetime_to_iso(user.created_at),
    }


def _export_collection(collection: Collection) -> dict[str, Any]:
    return {
        "id": collection.id,
        "name": collection.name,
        "user_id": collection.user_id,
        "is_default": collection.is_default,
        "position": collection.position,
        "created_at": _datetime_to_iso(collection.created_at),
    }


def _export_thread(thread: Thread) -> dict[str, Any]:
    return {
        "id": thread.id,
        "title": thread.title,
        "format": thread.format,
        "issues_remaining": thread.issues_remaining,
        "total_issues": thread.total_issues,
        "next_unread_issue_id": thread.next_unread_issue_id,
        "reading_progress": thread.reading_progress,
        "queue_position": thread.queue_position,
        "status": thread.status,
        "last_rating": thread.last_rating,
        "last_activity_at": _datetime_to_iso(thread.last_activity_at),
        "review_url": thread.review_url,
        "last_review_at": _datetime_to_iso(thread.last_review_at),
        "notes": thread.notes,
        "is_test": thread.is_test,
        "is_blocked": thread.is_blocked,
        "created_at": _datetime_to_iso(thread.created_at),
        "user_id": thread.user_id,
        "collection_id": thread.collection_id,
    }


def _export_issue(issue: Issue) -> dict[str, Any]:
    return {
        "id": issue.id,
        "thread_id": issue.thread_id,
        "issue_number": issue.issue_number,
        "position": issue.position,
        "status": issue.status,
        "read_at": _datetime_to_iso(issue.read_at),
        "created_at": _datetime_to_iso(issue.created_at),
    }


def _export_dependency(dependency: Dependency) -> dict[str, Any]:
    return {
        "id": dependency.id,
        "source_issue_id": dependency.source_issue_id,
        "target_issue_id": dependency.target_issue_id,
        "created_at": _datetime_to_iso(dependency.created_at),
        "note": dependency.note,
    }


def _export_reading_order(ro: ReadingOrder) -> dict[str, Any]:
    return {
        "id": ro.id,
        "name": ro.name,
        "description": ro.description,
        "user_id": ro.user_id,
    }


def _export_reading_order_item(item: ReadingOrderItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "reading_order_id": item.reading_order_id,
        "thread_id": item.thread_id,
        "position": item.position,
        "issue_number": item.issue_number,
    }


def _export_session(session: Session) -> dict[str, Any]:
    return {
        "id": session.id,
        "started_at": _datetime_to_iso(session.started_at),
        "ended_at": _datetime_to_iso(session.ended_at),
        "start_die": session.start_die,
        "manual_die": session.manual_die,
        "user_id": session.user_id,
        "pending_thread_id": session.pending_thread_id,
        "pending_issue_id": session.pending_issue_id,
        "pending_thread_updated_at": _datetime_to_iso(session.pending_thread_updated_at),
        "snoozed_thread_ids": session.snoozed_thread_ids,
    }


def _export_event(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "type": event.type,
        "timestamp": _datetime_to_iso(event.timestamp),
        "die": event.die,
        "result": event.result,
        "selected_thread_id": event.selected_thread_id,
        "selection_method": event.selection_method,
        "rating": event.rating,
        "issues_read": event.issues_read,
        "queue_move": event.queue_move,
        "die_after": event.die_after,
        "session_id": event.session_id,
        "thread_id": event.thread_id,
        "issue_id": event.issue_id,
        "issue_number": event.issue_number,
    }


def _export_snapshot(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "session_id": snapshot.session_id,
        "event_id": snapshot.event_id,
        "thread_states": snapshot.thread_states,
        "session_state": snapshot.session_state,
        "created_at": _datetime_to_iso(snapshot.created_at),
        "description": snapshot.description,
    }


def _export_review(review: Review) -> dict[str, Any]:
    return {
        "id": review.id,
        "user_id": review.user_id,
        "thread_id": review.thread_id,
        "issue_id": review.issue_id,
        "rating": review.rating,
        "review_text": review.review_text,
        "created_at": _datetime_to_iso(review.created_at),
        "updated_at": _datetime_to_iso(review.updated_at),
    }



async def _export_via_db(db_url: str, username: str) -> dict[str, Any]:
    engine = create_async_engine(db_url, pool_pre_ping=True)
    async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.username == username))
        users = list(result.scalars().all())

        if not users:
            target = username or "any"
            print(f"Error: No user found matching {target!r}", file=sys.stderr)
            sys.exit(1)

        source_user = users[0]
        user_id = source_user.id

        export: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "exported_at": datetime.now(UTC).isoformat(),
            "source": db_url.split("@")[-1] if "@" in db_url else db_url,
            "source_username": source_user.username,
            "user": _export_user(source_user),
        }

        result = await db.execute(
            select(Collection).where(Collection.user_id == user_id).order_by(Collection.id)
        )
        export["collections"] = [_export_collection(c) for c in result.scalars().all()]

        result = await db.execute(
            select(Thread).where(Thread.user_id == user_id).order_by(Thread.id)
        )
        threads = list(result.scalars().all())
        export["threads"] = [_export_thread(t) for t in threads]
        thread_ids = {t.id for t in threads}

        if thread_ids:
            result = await db.execute(
                select(Issue).where(Issue.thread_id.in_(thread_ids)).order_by(Issue.id)
            )
            issues = list(result.scalars().all())
            export["issues"] = [_export_issue(i) for i in issues]
        else:
            issues = []
            export["issues"] = []

        issue_ids = {i.id for i in issues}

        if issue_ids:
            result = await db.execute(
                select(Dependency)
                .where(Dependency.source_issue_id.in_(issue_ids))
                .order_by(Dependency.id)
            )
            export["dependencies"] = [_export_dependency(d) for d in result.scalars().all()]
        else:
            export["dependencies"] = []

        result = await db.execute(
            select(ReadingOrder).where(ReadingOrder.user_id == user_id).order_by(ReadingOrder.id)
        )
        reading_orders = list(result.scalars().all())
        export["reading_orders"] = [_export_reading_order(ro) for ro in reading_orders]

        if reading_orders:
            ro_ids = {ro.id for ro in reading_orders}
            result = await db.execute(
                select(ReadingOrderItem)
                .where(ReadingOrderItem.reading_order_id.in_(ro_ids))
                .order_by(ReadingOrderItem.id)
            )
            export["reading_order_items"] = [
                _export_reading_order_item(item) for item in result.scalars().all()
            ]
        else:
            export["reading_order_items"] = []

        result = await db.execute(
            select(Session).where(Session.user_id == user_id).order_by(Session.id)
        )
        sessions = list(result.scalars().all())
        export["sessions"] = [_export_session(s) for s in sessions]
        session_ids = {s.id for s in sessions}

        if session_ids:
            result = await db.execute(
                select(Event).where(Event.session_id.in_(session_ids)).order_by(Event.id)
            )
            events = list(result.scalars().all())
            export["events"] = [_export_event(e) for e in events]
        else:
            events = []
            export["events"] = []

        if session_ids:
            result = await db.execute(
                select(Snapshot).where(Snapshot.session_id.in_(session_ids)).order_by(Snapshot.id)
            )
            export["snapshots"] = [_export_snapshot(snap) for snap in result.scalars().all()]
        else:
            export["snapshots"] = []

        result = await db.execute(
            select(Review).where(Review.user_id == user_id).order_by(Review.id)
        )
        export["reviews"] = [_export_review(r) for r in result.scalars().all()]

    await engine.dispose()
    return export



def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backup production user data and restore it into local dev.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand")
    subparsers.required = True

    # export
    ep = subparsers.add_parser("export", help="Export user data from a database")
    ep.add_argument(
        "--db-url",
        default=os.environ.get("CLONE_PROD_DB_URL", ""),
        help="Database URL override (default: auto-fetch from Railway)",
    )
    ep.add_argument(
        "--username",
        default=os.environ.get("COMIC_PILE_USERNAME", ""),
        help="Production username (required)",
    )
    ep.add_argument(
        "-o", "--output",
        default=f"prod_backup_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json",
        help="Output file (default: prod_backup_<timestamp>.json)",
    )
    ep.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )

    # import
    imp = subparsers.add_parser("import", help="Restore backup into local dev database")
    imp.add_argument("-f", "--file", required=True, help="Backup JSON file to restore")
    imp.add_argument("--dry-run", action="store_true", help="Validate without writing")
    imp.add_argument("--backup", help="Path to write a pre-restore backup")
    imp.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    imp.add_argument(
        "--local-db-url",
        default="",
        help="Local database URL (default: from app.config)",
    )

    return parser


def _prompt_confirmation(message: str) -> bool:
    print(message)
    print()
    response = input("Type 'yes' to continue: ").strip().lower()
    return response == "yes"


def _print_summary(export: dict[str, Any]) -> None:
    counts: dict[str, int] = {}
    for key in EXPORT_TABLES:
        value = export.get(key, [])
        if isinstance(value, list):
            counts[key] = len(value)
        elif isinstance(value, dict) and value:
            counts[key] = 1
        else:
            counts[key] = 0

    print()
    print("Export summary:")
    print(f"  User:            {export.get('source_username', 'unknown')}")
    for key in EXPORT_TABLES:
        label = key.replace("_", " ").title()
        print(f"  {label:18s} {counts[key]}")
    print(f"  Schema version:  {export.get('schema_version', 'unknown')}")
    print(f"  Source:          {export.get('source', 'unknown')}")


async def _handle_export(args: argparse.Namespace) -> int:
    db_url = args.db_url

    if not db_url:
        db_url = _fetch_railway_db_url()

    # Convert scheme for async SQLAlchemy
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)

    username = args.username
    if not username:
        print("Error: --username is required.", file=sys.stderr)
        print("  Usage: python -m scripts.clone_prod_to_local export --username Josh", file=sys.stderr)
        return 1

    if not args.yes:
        host = db_url.split("@")[-1].split("?")[0] if "@" in db_url else db_url[:60]
        if not _prompt_confirmation(
            f"This will READ all data from {host}. Continue?"
        ):
            print("Cancelled.")
            return 0

    print("Exporting...")
    export = await _export_via_db(db_url, username)

    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(export, f, cls=_DateTimeEncoder, indent=2)

    _print_summary(export)
    print(f"Wrote {output_path.resolve()}")
    return 0


async def _handle_import(args: argparse.Namespace) -> int:
    print("Import not yet implemented.", file=sys.stderr)
    return 1


async def _async_main(args: argparse.Namespace) -> int:
    if args.command == "export":
        return await _handle_export(args)
    elif args.command == "import":
        return await _handle_import(args)
    return 1


def main() -> int:
    """Entry point: parse args and run the selected subcommand."""
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
