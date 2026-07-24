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
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlparse

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



class ExportUserRecord(TypedDict, total=False):
    """Serialized user record for export."""

    id: int
    username: str
    email: str
    is_admin: bool
    created_at: str | None


class ExportCollectionRecord(TypedDict, total=False):
    """Serialized collection record for export."""

    id: int
    name: str
    user_id: int
    is_default: bool
    position: int
    created_at: str | None


class ExportThreadRecord(TypedDict, total=False):
    """Serialized thread record for export."""

    id: int
    title: str
    format: str
    issues_remaining: int
    total_issues: int
    next_unread_issue_id: int | None
    reading_progress: float
    queue_position: int
    status: str
    last_rating: float | None
    last_activity_at: str | None
    review_url: str | None
    last_review_at: str | None
    notes: str | None
    is_test: bool
    is_blocked: bool
    created_at: str | None
    user_id: int
    collection_id: int | None


class ExportIssueRecord(TypedDict, total=False):
    """Serialized issue record for export."""

    id: int
    thread_id: int
    issue_number: int
    position: int
    status: str
    read_at: str | None
    created_at: str | None


class ExportDependencyRecord(TypedDict, total=False):
    """Serialized dependency record for export."""

    id: int
    source_issue_id: int
    target_issue_id: int
    created_at: str | None
    note: str | None


class ExportReadingOrderRecord(TypedDict, total=False):
    """Serialized reading order record for export."""

    id: int
    name: str
    description: str | None
    user_id: int


class ExportReadingOrderItemRecord(TypedDict, total=False):
    """Serialized reading order item record for export."""

    id: int
    reading_order_id: int
    thread_id: int
    position: int
    issue_number: int


class ExportSessionRecord(TypedDict, total=False):
    """Serialized session record for export."""

    id: int
    started_at: str | None
    ended_at: str | None
    start_die: int
    manual_die: int
    user_id: int
    pending_thread_id: int | None
    pending_issue_id: int | None
    pending_thread_updated_at: str | None
    snoozed_thread_ids: list[int] | None


class ExportEventRecord(TypedDict, total=False):
    """Serialized event record for export."""

    id: int
    type: str
    timestamp: str | None
    die: int
    result: str | None
    selected_thread_id: int | None
    selection_method: str | None
    rating: float | None
    issues_read: int | None
    queue_move: int | None
    die_after: bool | None
    session_id: int
    thread_id: int | None
    issue_id: int | None
    issue_number: int | None


class ExportSnapshotRecord(TypedDict, total=False):
    """Serialized snapshot record for export."""

    id: int
    session_id: int
    event_id: int | None
    thread_states: dict[str, Any]
    session_state: dict[str, Any]
    created_at: str | None
    description: str | None


class ExportReviewRecord(TypedDict, total=False):
    """Serialized review record for export."""

    id: int
    user_id: int
    thread_id: int
    issue_id: int
    rating: float | None
    review_text: str | None
    created_at: str | None
    updated_at: str | None


class ExportDocument(TypedDict):
    """Top-level versioned export document."""

    schema_version: str
    exported_at: str
    source_url: str
    source_username: str
    user: ExportUserRecord
    collections: list[ExportCollectionRecord]
    threads: list[ExportThreadRecord]
    issues: list[ExportIssueRecord]
    dependencies: list[ExportDependencyRecord]
    reading_orders: list[ExportReadingOrderRecord]
    reading_order_items: list[ExportReadingOrderItemRecord]
    sessions: list[ExportSessionRecord]
    events: list[ExportEventRecord]
    snapshots: list[ExportSnapshotRecord]
    reviews: list[ExportReviewRecord]


class _DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects."""

    def default(self, o: object) -> str | int | float | bool | list[object] | dict[str, object] | None:
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def _redact_db_url(db_url: str) -> str:
    """Return a credential-free description of the database target."""
    try:
        parsed = urlparse(db_url)
        host = parsed.hostname or "unknown"
        port = parsed.port or 5432
        database = parsed.path.lstrip("/") or "unknown"
        return f"{host}:{port}/{database}"
    except Exception:
        return "(unable to parse database URL)"


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



async def _export_via_db(db_url: str, username: str) -> ExportDocument:
    engine = create_async_engine(
        db_url,
        pool_pre_ping=True,
        isolation_level="REPEATABLE READ",
        connect_args={
            "server_settings": {
                "default_transaction_read_only": "on",
            }
        },
    )
    async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    async with async_session_factory() as db:

        result = await db.execute(select(User).where(User.username == username))
        users = list(result.scalars().all())

        if not users:
            target = username or "any"
            print(f"Error: No user found matching {target!r}", file=sys.stderr)
            sys.exit(1)

        source_user = users[0]
        user_id = source_user.id

        export: ExportDocument = {
            "schema_version": SCHEMA_VERSION,
            "exported_at": datetime.now(UTC).isoformat(),
            "source_url": _redact_db_url(db_url),
            "source_username": source_user.username,
            "user": _export_user(source_user),
            "collections": [],
            "threads": [],
            "issues": [],
            "dependencies": [],
            "reading_orders": [],
            "reading_order_items": [],
            "sessions": [],
            "events": [],
            "snapshots": [],
            "reviews": [],
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

        issue_ids = {i.id for i in issues}

        if issue_ids:
            result = await db.execute(
                select(Dependency)
                .where(
                    Dependency.source_issue_id.in_(issue_ids),
                    Dependency.target_issue_id.in_(issue_ids),
                )
                .order_by(Dependency.id)
            )
            export["dependencies"] = [_export_dependency(d) for d in result.scalars().all()]

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
            export["events"] = [_export_event(e) for e in result.scalars().all()]

            result = await db.execute(
                select(Snapshot).where(Snapshot.session_id.in_(session_ids)).order_by(Snapshot.id)
            )
            export["snapshots"] = [_export_snapshot(snap) for snap in result.scalars().all()]

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
        if key == "user":
            continue
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
        if key == "user":
            continue
        label = key.replace("_", " ").title()
        print(f"  {label:18s} {counts[key]}")
    print(f"  Schema version:  {export.get('schema_version', 'unknown')}")
    print(f"  Source:          {export.get('source_url', 'unknown')}")


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

    target = _redact_db_url(db_url)
    if not args.yes:
        if not _prompt_confirmation(
            f"This will READ all data from {target}. Continue?"
        ):
            print("Cancelled.")
            return 0
    else:
        print(f"Target: {target}")

    print("Exporting...")
    export = await _export_via_db(db_url, username)

    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(export, f, cls=_DateTimeEncoder, indent=2)
    os.chmod(output_path, stat.S_IRUSR | stat.S_IWUSR)

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
