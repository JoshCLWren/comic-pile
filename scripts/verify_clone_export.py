#!/usr/bin/env python3
"""Validate a ComicPile production-to-local export without touching a database."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

SUPPORTED_SCHEMA_VERSION: Final = "1.0"
REQUIRED_LISTS: Final = (
    "threads",
    "issues",
    "dependencies",
    "reading_orders",
    "reading_order_items",
    "sessions",
    "events",
    "snapshots",
)
FORBIDDEN_TOP_LEVEL_KEYS: Final = {
    "collections",
    "collection_items",
    "collection_memberships",
    "refresh_tokens",
    "tokens",
    "auth_tokens",
}
SENSITIVE_KEY_FRAGMENTS: Final = (
    "password",
    "refresh_token",
    "access_token",
    "api_key",
    "secret",
)


class ExportValidationError(ValueError):
    """Raised when an export document is unsafe or internally inconsistent."""


def _records(document: Mapping[str, object], name: str) -> list[Mapping[str, object]]:
    value = document.get(name)
    if not isinstance(value, list):
        raise ExportValidationError(f"{name} must be a list")
    records: list[Mapping[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ExportValidationError(f"{name}[{index}] must be an object")
        records.append(item)
    return records


def _integer_ids(records: Iterable[Mapping[str, object]], table: str) -> set[int]:
    ids: set[int] = set()
    for index, record in enumerate(records):
        value = record.get("id")
        if not isinstance(value, int) or isinstance(value, bool):
            raise ExportValidationError(f"{table}[{index}].id must be an integer")
        if value in ids:
            raise ExportValidationError(f"{table} contains duplicate id {value}")
        ids.add(value)
    return ids


def _require_reference(
    record: Mapping[str, object],
    field: str,
    valid_ids: set[int],
    location: str,
    *,
    nullable: bool = False,
) -> None:
    value = record.get(field)
    if value is None and nullable:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise ExportValidationError(f"{location}.{field} must be an integer")
    if value not in valid_ids:
        raise ExportValidationError(f"{location}.{field} references missing id {value}")


def _reject_sensitive_keys(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS):
                raise ExportValidationError(f"sensitive field is forbidden at {path}.{key}")
            _reject_sensitive_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_keys(child, f"{path}[{index}]")


def validate_export(document: Mapping[str, object]) -> dict[str, int]:
    """Validate schema, secret exclusion, IDs, and retained-data references."""
    version = document.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ExportValidationError(
            f"unsupported schema_version {version!r}; expected {SUPPORTED_SCHEMA_VERSION!r}"
        )

    forbidden = FORBIDDEN_TOP_LEVEL_KEYS.intersection(document)
    if forbidden:
        raise ExportValidationError(
            "Collections or auth payloads are forbidden: " + ", ".join(sorted(forbidden))
        )

    _reject_sensitive_keys(document)

    user = document.get("user")
    if not isinstance(user, dict):
        raise ExportValidationError("user must be an object")
    user_id = user.get("id")
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        raise ExportValidationError("user.id must be an integer")

    tables = {name: _records(document, name) for name in REQUIRED_LISTS}
    ids = {name: _integer_ids(records, name) for name, records in tables.items()}

    for index, thread in enumerate(tables["threads"]):
        _require_reference(thread, "user_id", {user_id}, f"threads[{index}]")
        _require_reference(
            thread,
            "next_unread_issue_id",
            ids["issues"],
            f"threads[{index}]",
            nullable=True,
        )

    for index, issue in enumerate(tables["issues"]):
        _require_reference(issue, "thread_id", ids["threads"], f"issues[{index}]")

    for index, dependency in enumerate(tables["dependencies"]):
        _require_reference(
            dependency, "source_issue_id", ids["issues"], f"dependencies[{index}]"
        )
        _require_reference(
            dependency, "target_issue_id", ids["issues"], f"dependencies[{index}]"
        )

    for index, order in enumerate(tables["reading_orders"]):
        _require_reference(order, "user_id", {user_id}, f"reading_orders[{index}]")

    for index, item in enumerate(tables["reading_order_items"]):
        _require_reference(
            item, "reading_order_id", ids["reading_orders"], f"reading_order_items[{index}]"
        )
        _require_reference(item, "thread_id", ids["threads"], f"reading_order_items[{index}]")

    for index, session in enumerate(tables["sessions"]):
        location = f"sessions[{index}]"
        _require_reference(session, "user_id", {user_id}, location)
        _require_reference(
            session, "pending_thread_id", ids["threads"], location, nullable=True
        )
        _require_reference(session, "pending_issue_id", ids["issues"], location, nullable=True)
        snoozed_ids = session.get("snoozed_thread_ids")
        if snoozed_ids is not None:
            if not isinstance(snoozed_ids, list):
                raise ExportValidationError(f"{location}.snoozed_thread_ids must be a list")
            for snoozed_index, thread_id in enumerate(snoozed_ids):
                if thread_id not in ids["threads"]:
                    raise ExportValidationError(
                        f"{location}.snoozed_thread_ids[{snoozed_index}] references "
                        f"missing id {thread_id}"
                    )

    for index, event in enumerate(tables["events"]):
        location = f"events[{index}]"
        _require_reference(event, "session_id", ids["sessions"], location)
        _require_reference(event, "thread_id", ids["threads"], location, nullable=True)
        _require_reference(
            event, "selected_thread_id", ids["threads"], location, nullable=True
        )
        _require_reference(event, "issue_id", ids["issues"], location, nullable=True)

    for index, snapshot in enumerate(tables["snapshots"]):
        _require_reference(snapshot, "session_id", ids["sessions"], f"snapshots[{index}]")
        _require_reference(snapshot, "event_id", ids["events"], f"snapshots[{index}]", nullable=True)

    return {name: len(records) for name, records in tables.items()}


def main() -> int:
    """Validate one export JSON file and print deterministic record counts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="Export JSON produced by clone_prod_to_local")
    args = parser.parse_args()

    try:
        raw = json.loads(args.file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ExportValidationError("export root must be an object")
        counts = validate_export(raw)
    except (OSError, json.JSONDecodeError, ExportValidationError) as exc:
        parser.exit(1, f"INVALID: {exc}\n")

    print("VALID clone export")
    for name in REQUIRED_LISTS:
        print(f"{name}: {counts[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
