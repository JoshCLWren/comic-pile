#!/usr/bin/env python3
"""Backup production user data and restore it into local dev.

Exports the authenticated user's data (threads, issues, sessions, etc.)
from a production PostgreSQL database into a structured JSON file, then
restores it into the local development database with ID remapping.

Never mutates production data. Never exports password hashes or auth tokens.

Usage:
    # Export from an explicit production Neon URL:
    python -m scripts.clone_prod_to_local export --username Josh --db-url postgresql+asyncpg://...

    # Or provide the source through CLONE_PROD_DB_URL:
    CLONE_PROD_DB_URL=postgresql+asyncpg://... \
        python -m scripts.clone_prod_to_local export --username Josh

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
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import urlparse

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    Dependency,
    Event,
    Issue,
    ReadingOrder,
    ReadingOrderItem,
    Session,
    Snapshot,
    Thread,
    User,
)
from scripts.database_target_safety import require_local_database_url


SCHEMA_VERSION = "1.0"

EXPORT_TABLES = [
    "user",
    "threads",
    "issues",
    "dependencies",
    "reading_orders",
    "reading_order_items",
    "sessions",
    "events",
    "snapshots",
]

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


def _async_database_url(db_url: str) -> str:
    """Return a PostgreSQL URL using the asyncpg driver."""
    for source in ("postgresql://", "postgres://", "postgresql+psycopg://"):
        if db_url.startswith(source):
            return db_url.replace(source, "postgresql+asyncpg://", 1)
    return db_url


class ExportUserRecord(TypedDict, total=False):
    """Serialized user record for export."""

    id: int
    username: str
    email: str
    is_admin: bool
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
    notes: str | None
    is_test: bool
    is_blocked: bool
    created_at: str | None
    user_id: int


class ExportIssueRecord(TypedDict, total=False):
    """Serialized issue record for export."""

    id: int
    thread_id: int
    issue_number: str
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
    issue_number: str


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
    result: int | None
    selected_thread_id: int | None
    selection_method: str | None
    rating: float | None
    issues_read: int | None
    queue_move: str | None
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
    thread_states: dict[str, JsonValue]
    session_state: dict[str, JsonValue] | None
    created_at: str | None
    description: str | None


class ExportDocument(TypedDict):
    """Top-level versioned export document."""

    schema_version: str
    exported_at: str
    source_url: str
    source_username: str
    user: ExportUserRecord
    threads: list[ExportThreadRecord]
    issues: list[ExportIssueRecord]
    dependencies: list[ExportDependencyRecord]
    reading_orders: list[ExportReadingOrderRecord]
    reading_order_items: list[ExportReadingOrderItemRecord]
    sessions: list[ExportSessionRecord]
    events: list[ExportEventRecord]
    snapshots: list[ExportSnapshotRecord]


type ExportRecord = (
    ExportThreadRecord
    | ExportIssueRecord
    | ExportDependencyRecord
    | ExportReadingOrderRecord
    | ExportReadingOrderItemRecord
    | ExportSessionRecord
    | ExportEventRecord
    | ExportSnapshotRecord
)


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


def _datetime_to_iso(obj: object) -> str | None:
    if isinstance(obj, datetime):
        return obj.isoformat()
    return None


def _export_user(user: User) -> ExportUserRecord:
    return ExportUserRecord(**{
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "created_at": _datetime_to_iso(user.created_at),
    })


def _export_thread(thread: Thread) -> ExportThreadRecord:
    return ExportThreadRecord(**{
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
        "notes": thread.notes,
        "is_test": thread.is_test,
        "is_blocked": thread.is_blocked,
        "created_at": _datetime_to_iso(thread.created_at),
        "user_id": thread.user_id,
    })


def _export_issue(issue: Issue) -> ExportIssueRecord:
    return ExportIssueRecord(**{
        "id": issue.id,
        "thread_id": issue.thread_id,
        "issue_number": issue.issue_number,
        "position": issue.position,
        "status": issue.status,
        "read_at": _datetime_to_iso(issue.read_at),
        "created_at": _datetime_to_iso(issue.created_at),
    })


def _export_dependency(dependency: Dependency) -> ExportDependencyRecord:
    return ExportDependencyRecord(**{
        "id": dependency.id,
        "source_issue_id": dependency.source_issue_id,
        "target_issue_id": dependency.target_issue_id,
        "created_at": _datetime_to_iso(dependency.created_at),
        "note": dependency.note,
    })


def _export_reading_order(ro: ReadingOrder) -> ExportReadingOrderRecord:
    return ExportReadingOrderRecord(**{
        "id": ro.id,
        "name": ro.name,
        "description": ro.description,
        "user_id": ro.user_id,
    })


def _export_reading_order_item(item: ReadingOrderItem) -> ExportReadingOrderItemRecord:
    return ExportReadingOrderItemRecord(**{
        "id": item.id,
        "reading_order_id": item.reading_order_id,
        "thread_id": item.thread_id,
        "position": item.position,
        "issue_number": item.issue_number,
    })


def _export_session(session: Session) -> ExportSessionRecord:
    return ExportSessionRecord(**{
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
    })


def _export_event(event: Event) -> ExportEventRecord:
    return ExportEventRecord(**{
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
    })


def _export_snapshot(snapshot: Snapshot) -> ExportSnapshotRecord:
    return ExportSnapshotRecord(**{
        "id": snapshot.id,
        "session_id": snapshot.session_id,
        "event_id": snapshot.event_id,
        "thread_states": cast(dict[str, JsonValue], snapshot.thread_states),
        "session_state": cast(dict[str, JsonValue] | None, snapshot.session_state),
        "created_at": _datetime_to_iso(snapshot.created_at),
        "description": snapshot.description,
    })


def _records_for_table(export: ExportDocument, table: str) -> list[ExportRecord]:
    """Return typed records for a non-user export table."""
    records: object
    match table:
        case "threads":
            records = export["threads"]
        case "issues":
            records = export["issues"]
        case "dependencies":
            records = export["dependencies"]
        case "reading_orders":
            records = export["reading_orders"]
        case "reading_order_items":
            records = export["reading_order_items"]
        case "sessions":
            records = export["sessions"]
        case "events":
            records = export["events"]
        case "snapshots":
            records = export["snapshots"]
        case _:
            raise ValueError(f"Unsupported export table {table!r}")
    return cast(list[ExportRecord], records)


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
            "threads": [],
            "issues": [],
            "dependencies": [],
            "reading_orders": [],
            "reading_order_items": [],
            "sessions": [],
            "events": [],
            "snapshots": [],
        }

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

    await engine.dispose()
    return export


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an exported ISO timestamp, preserving null values."""
    return datetime.fromisoformat(value) if value else None


def _validate_export(export: ExportDocument) -> None:
    """Validate schema version and all exported foreign-key references."""
    if export.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported schema version {export.get('schema_version')!r}; expected {SCHEMA_VERSION!r}"
        )
    user = export.get("user")
    if (
        not isinstance(user, dict)
        or not isinstance(user.get("id"), int)
        or not isinstance(user.get("username"), str)
        or not user["username"].strip()
    ):
        raise ValueError("Export must contain a user with an integer id and username")

    list_keys = [key for key in EXPORT_TABLES if key != "user"]
    for key in list_keys:
        if not isinstance(export.get(key), list):
            raise ValueError(f"Export field {key!r} must be a list")

    ids: dict[str, set[int]] = {key: set() for key in list_keys}
    for key in list_keys:
        for record in _records_for_table(export, key):
            if not isinstance(record, dict) or not isinstance(record.get("id"), int):
                raise ValueError(f"Every {key} record must have an integer id")
            record_id = record["id"]
            if record_id in ids[key]:
                raise ValueError(f"Duplicate {key} id {record_id}")
            ids[key].add(record_id)

    user_id = user["id"]
    checks = {
        "threads": [("user_id", "user")],
        "issues": [("thread_id", "threads")],
        "dependencies": [
            ("source_issue_id", "issues"),
            ("target_issue_id", "issues"),
        ],
        "reading_orders": [("user_id", "user")],
        "reading_order_items": [
            ("reading_order_id", "reading_orders"),
            ("thread_id", "threads"),
        ],
        "sessions": [
            ("user_id", "user"),
            ("pending_thread_id", "threads"),
            ("pending_issue_id", "issues"),
        ],
        "events": [
            ("session_id", "sessions"),
            ("thread_id", "threads"),
            ("issue_id", "issues"),
        ],
        "snapshots": [("session_id", "sessions"), ("event_id", "events")],
    }
    for table, fields in checks.items():
        for record in _records_for_table(export, table):
            for field, target in fields:
                value = record.get(field)
                if value is None and field.endswith("_id"):
                    continue
                target_ids = {user_id} if target == "user" else ids[target]
                if not isinstance(value, int) or value not in target_ids:
                    raise ValueError(f"{table}.{field} references missing {target} id {value!r}")
    issue_ids = ids["issues"]
    thread_ids = ids["threads"]
    for record in export["threads"]:
        value = record.get("next_unread_issue_id")
        if value is not None and value not in issue_ids:
            raise ValueError(f"threads.next_unread_issue_id references missing issue id {value!r}")
    for record in export["sessions"]:
        values = record.get("snoozed_thread_ids") or []
        if any(value not in thread_ids for value in values):
            raise ValueError("sessions.snoozed_thread_ids references a missing thread")


def _remap(value: int | None, mapping: dict[int, int]) -> int | None:
    """Remap a nullable exported identifier."""
    return mapping.get(value) if value is not None else None


async def _delete_local_user_data(db: AsyncSession, user_id: int) -> None:
    """Delete the local user's imported data in foreign-key-safe order."""
    thread_ids = select(Thread.id).where(Thread.user_id == user_id)
    issue_ids = select(Issue.id).where(Issue.thread_id.in_(thread_ids))
    session_ids = select(Session.id).where(Session.user_id == user_id)
    order_ids = select(ReadingOrder.id).where(ReadingOrder.user_id == user_id)
    await db.execute(delete(Snapshot).where(Snapshot.session_id.in_(session_ids)))
    await db.execute(delete(Event).where(Event.session_id.in_(session_ids)))
    await db.execute(delete(ReadingOrderItem).where(ReadingOrderItem.reading_order_id.in_(order_ids)))
    await db.execute(delete(ReadingOrder).where(ReadingOrder.user_id == user_id))
    await db.execute(delete(Dependency).where(
        Dependency.source_issue_id.in_(issue_ids) | Dependency.target_issue_id.in_(issue_ids)
    ))
    await db.execute(delete(Session).where(Session.user_id == user_id))
    await db.execute(delete(Issue).where(Issue.thread_id.in_(thread_ids)))
    await db.execute(delete(Thread).where(Thread.user_id == user_id))


async def _sync_id_sequences(db: AsyncSession) -> None:
    """Advance PostgreSQL identity sequences after importing explicit record IDs."""
    tables = (
        "users",
        "threads",
        "issues",
        "dependencies",
        "reading_orders",
        "reading_order_items",
        "sessions",
        "events",
        "snapshots",
    )
    for table in tables:
        await db.execute(
            text(
                "SELECT setval("
                f"pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                f"(SELECT MAX(id) IS NOT NULL FROM {table}))"
            )
        )


async def _import_document(
    db_url: str,
    export: ExportDocument,
    backup_path: Path | None,
    dry_run: bool,
) -> dict[str, int]:
    """Validate and import an export document, returning post-import counts."""
    require_local_database_url(db_url)
    _validate_export(export)
    engine = create_async_engine(_async_database_url(db_url), pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            result = await db.execute(select(User).where(User.username == export["user"]["username"]))
            existing_user = result.scalar_one_or_none()
            existing_user_id = existing_user.id if existing_user is not None else None
            if dry_run:
                print("Dry run: validated export; no database changes made.")
                return {
                    key: len(_records_for_table(export, key))
                    for key in EXPORT_TABLES
                    if key != "user"
                }

            if backup_path is not None:
                if existing_user is None:
                    backup = {
                        "schema_version": SCHEMA_VERSION,
                        "exported_at": datetime.now(UTC).isoformat(),
                        "source_url": _redact_db_url(db_url),
                        "source_username": export["user"]["username"],
                        "user": {},
                        **{key: [] for key in EXPORT_TABLES if key != "user"},
                    }
                else:
                    backup = await _export_via_db(_async_database_url(db_url), export["user"]["username"])
                _write_json(backup_path, backup)
                print(f"Pre-import backup: {backup_path.resolve()}")

            await db.rollback()
            await _sync_id_sequences(db)
            await db.commit()
            async with db.begin():
                if existing_user_id is None:
                    local_user = User(
                        username=export["user"]["username"],
                        email=export["user"].get("email"),
                        is_admin=export["user"].get("is_admin", False),
                        created_at=_parse_datetime(export["user"].get("created_at")) or datetime.now(UTC),
                    )
                    db.add(local_user)
                    await db.flush()
                else:
                    local_user = await db.get(User, existing_user_id)
                    if local_user is None:
                        raise ValueError(f"Local user {existing_user_id} disappeared before import")
                    await _delete_local_user_data(db, local_user.id)
                    local_user.email = export["user"].get("email")
                    local_user.is_admin = export["user"].get("is_admin", False)
                    local_user.created_at = (
                        _parse_datetime(export["user"].get("created_at")) or local_user.created_at
                    )

                thread_map: dict[int, int] = {}
                thread_models: dict[int, Thread] = {}
                for record in export["threads"]:
                    item = Thread(
                        title=record["title"], format=record["format"], issues_remaining=record.get("issues_remaining", 0),
                        total_issues=record.get("total_issues"), next_unread_issue_id=None,
                        reading_progress=record.get("reading_progress"), queue_position=record.get("queue_position", 0),
                        status=record.get("status", "active"), last_rating=record.get("last_rating"),
                        last_activity_at=_parse_datetime(record.get("last_activity_at")), notes=record.get("notes"),
                        is_test=record.get("is_test", False), is_blocked=record.get("is_blocked", False),
                        created_at=_parse_datetime(record.get("created_at")) or datetime.now(UTC),
                        user_id=local_user.id,
                    )
                    db.add(item)
                    await db.flush()
                    thread_map[record["id"]] = item.id
                    thread_models[record["id"]] = item

                issue_map: dict[int, int] = {}
                for record in export["issues"]:
                    item = Issue(
                        thread_id=thread_map[record["thread_id"]], issue_number=str(record["issue_number"]),
                        position=record.get("position", 0), status=record.get("status", "unread"),
                        read_at=_parse_datetime(record.get("read_at")), created_at=_parse_datetime(record.get("created_at")) or datetime.now(UTC),
                    )
                    db.add(item)
                    await db.flush()
                    issue_map[record["id"]] = item.id

                for record in export["threads"]:
                    thread_models[record["id"]].next_unread_issue_id = _remap(record.get("next_unread_issue_id"), issue_map)
                await db.flush()

                for record in export["dependencies"]:
                    db.add(Dependency(
                        source_issue_id=issue_map[record["source_issue_id"]], target_issue_id=issue_map[record["target_issue_id"]],
                        created_at=_parse_datetime(record.get("created_at")) or datetime.now(UTC), note=record.get("note"),
                    ))
                await db.flush()

                order_map: dict[int, int] = {}
                for record in export["reading_orders"]:
                    item = ReadingOrder(name=record["name"], description=record.get("description"), user_id=local_user.id)
                    db.add(item)
                    await db.flush()
                    order_map[record["id"]] = item.id
                for record in export["reading_order_items"]:
                    db.add(ReadingOrderItem(
                        reading_order_id=order_map[record["reading_order_id"]], thread_id=thread_map[record["thread_id"]],
                        position=record["position"], issue_number=record.get("issue_number"),
                    ))

                session_map: dict[int, int] = {}
                for record in export["sessions"]:
                    snoozed = record.get("snoozed_thread_ids")
                    item = Session(
                        started_at=_parse_datetime(record.get("started_at")) or datetime.now(UTC), ended_at=_parse_datetime(record.get("ended_at")),
                        start_die=record.get("start_die", 6), manual_die=record.get("manual_die"), user_id=local_user.id,
                        pending_thread_id=_remap(record.get("pending_thread_id"), thread_map), pending_issue_id=_remap(record.get("pending_issue_id"), issue_map),
                        pending_thread_updated_at=_parse_datetime(record.get("pending_thread_updated_at")),
                        snoozed_thread_ids=[thread_map.get(value, value) for value in snoozed] if snoozed else snoozed,
                    )
                    db.add(item)
                    await db.flush()
                    session_map[record["id"]] = item.id
                event_map: dict[int, int] = {}
                for record in export["events"]:
                    selected_thread_id = record.get("selected_thread_id")
                    item = Event(
                        type=record["type"], timestamp=_parse_datetime(record.get("timestamp")) or datetime.now(UTC), die=record.get("die"),
                        result=record.get("result"),
                        selected_thread_id=(
                            thread_map.get(selected_thread_id)
                            if selected_thread_id is not None
                            else None
                        ),
                        selection_method=record.get("selection_method"), rating=record.get("rating"), issues_read=record.get("issues_read"),
                        queue_move=record.get("queue_move"), die_after=record.get("die_after"), session_id=_remap(record.get("session_id"), session_map),
                        thread_id=_remap(record.get("thread_id"), thread_map), issue_id=_remap(record.get("issue_id"), issue_map), issue_number=record.get("issue_number"),
                    )
                    db.add(item)
                    await db.flush()
                    event_map[record["id"]] = item.id
                for record in export["snapshots"]:
                    db.add(Snapshot(
                        session_id=session_map[record["session_id"]], event_id=_remap(record.get("event_id"), event_map),
                        thread_states=record.get("thread_states", {}), session_state=record.get("session_state"),
                        created_at=_parse_datetime(record.get("created_at")) or datetime.now(UTC), description=record.get("description"),
                    ))
                await db.flush()

            await _sync_id_sequences(db)
            await db.commit()

            counts = {
                key: len(_records_for_table(export, key))
                for key in EXPORT_TABLES
                if key != "user"
            }
            return counts
    finally:
        await engine.dispose()


def _write_json(path: Path, document: ExportDocument) -> None:
    """Write a private JSON export file."""
    with path.open("w") as output:
        json.dump(document, output, cls=_DateTimeEncoder, indent=2)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


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
        help="Production Neon database URL (required, or set CLONE_PROD_DB_URL)",
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


def _print_summary(export: ExportDocument) -> None:
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
        print(
            "Error: --db-url or CLONE_PROD_DB_URL is required; Railway fallback is unsupported.",
            file=sys.stderr,
        )
        return 1

    db_url = _async_database_url(db_url)

    username = args.username
    if not username:
        print("Error: --username is required.", file=sys.stderr)
        print(
            "  Usage: python -m scripts.clone_prod_to_local export --username Josh --db-url <neon-url>",
            file=sys.stderr,
        )
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
    input_path = Path(args.file)
    try:
        with input_path.open() as source:
            parsed: object = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        print(f"Error: unable to read export file {input_path}: {error}", file=sys.stderr)
        return 1
    if not isinstance(parsed, dict):
        print("Error: export file must contain a JSON object.", file=sys.stderr)
        return 1
    export = cast(ExportDocument, parsed)

    db_url = args.local_db_url
    if not db_url:
        from app.config import get_database_settings

        db_url = get_database_settings().async_url
    db_url = _async_database_url(db_url)
    try:
        require_local_database_url(db_url)
        _validate_export(export)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    _print_summary(export)
    if args.dry_run:
        counts = await _import_document(db_url, export, None, dry_run=True)
        print(f"Validated counts: {counts}")
        return 0

    backup_path = Path(args.backup) if args.backup else Path(
        f"local_backup_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    )
    if not args.yes and not _prompt_confirmation(
        f"This will replace data for user {export['user']['username']!r} in {_redact_db_url(db_url)}. Continue?"
    ):
        print("Cancelled.")
        return 0
    try:
        counts = await _import_document(db_url, export, backup_path, dry_run=False)
    except Exception as error:
        print(f"Error: import failed and was rolled back: {error}", file=sys.stderr)
        return 1
    print("Import completed. Post-import counts:")
    for key, count in counts.items():
        print(f"  {key.replace('_', ' ').title():18s} {count}")
    return 0


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
