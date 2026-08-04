#!/usr/bin/env python3
"""Plan a production-to-local clone restore without mutating a database."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

TABLE_ORDER: Final = (
    "threads",
    "issues",
    "dependencies",
    "reading_orders",
    "reading_order_items",
    "sessions",
    "events",
    "snapshots",
)


class RestorePlanError(ValueError):
    """Raised when a safe deterministic restore plan cannot be produced."""


@dataclass(frozen=True)
class TableRestorePlan:
    """Describe one table's deterministic restore work."""

    table: str
    source_count: int
    first_local_id: int | None
    last_local_id: int | None
    id_map: dict[int, int]


@dataclass(frozen=True)
class RestorePlan:
    """Describe the complete database-free restore plan."""

    source_username: str
    local_user_id: int
    insertion_order: tuple[str, ...]
    tables: tuple[TableRestorePlan, ...]


def _records(document: Mapping[str, object], table: str) -> list[Mapping[str, object]]:
    value = document.get(table)
    if not isinstance(value, list):
        raise RestorePlanError(f"{table} must be a list")
    records: list[Mapping[str, object]] = []
    for index, record in enumerate(value):
        if not isinstance(record, dict):
            raise RestorePlanError(f"{table}[{index}] must be an object")
        records.append(record)
    return records


def _source_ids(records: Sequence[Mapping[str, object]], table: str) -> list[int]:
    source_ids: list[int] = []
    seen: set[int] = set()
    for index, record in enumerate(records):
        source_id = record.get("id")
        if not isinstance(source_id, int) or isinstance(source_id, bool):
            raise RestorePlanError(f"{table}[{index}].id must be an integer")
        if source_id in seen:
            raise RestorePlanError(f"{table} contains duplicate id {source_id}")
        seen.add(source_id)
        source_ids.append(source_id)
    return sorted(source_ids)


def build_restore_plan(
    document: Mapping[str, object],
    *,
    local_user_id: int,
    next_ids: Mapping[str, int],
) -> RestorePlan:
    """Build stable source-to-local ID maps without writing to a database."""
    if local_user_id <= 0:
        raise RestorePlanError("local_user_id must be positive")

    source_username = document.get("source_username")
    if not isinstance(source_username, str) or not source_username.strip():
        raise RestorePlanError("source_username must be a non-empty string")

    user = document.get("user")
    if not isinstance(user, dict):
        raise RestorePlanError("user must be an object")
    source_user_id = user.get("id")
    if not isinstance(source_user_id, int) or isinstance(source_user_id, bool):
        raise RestorePlanError("user.id must be an integer")

    plans: list[TableRestorePlan] = []
    for table in TABLE_ORDER:
        records = _records(document, table)
        source_ids = _source_ids(records, table)
        start = next_ids.get(table)
        if not isinstance(start, int) or isinstance(start, bool) or start <= 0:
            raise RestorePlanError(f"next_ids[{table!r}] must be a positive integer")
        id_map = {source_id: start + offset for offset, source_id in enumerate(source_ids)}
        plans.append(
            TableRestorePlan(
                table=table,
                source_count=len(source_ids),
                first_local_id=start if source_ids else None,
                last_local_id=start + len(source_ids) - 1 if source_ids else None,
                id_map=id_map,
            )
        )

    thread_ids = {record["id"] for record in _records(document, "threads")}
    for index, thread in enumerate(_records(document, "threads")):
        if thread.get("user_id") != source_user_id:
            raise RestorePlanError(f"threads[{index}].user_id is not owned by export user")
    for index, order in enumerate(_records(document, "reading_orders")):
        if order.get("user_id") != source_user_id:
            raise RestorePlanError(f"reading_orders[{index}].user_id is not owned by export user")
    for index, session in enumerate(_records(document, "sessions")):
        if session.get("user_id") != source_user_id:
            raise RestorePlanError(f"sessions[{index}].user_id is not owned by export user")
        snoozed = session.get("snoozed_thread_ids")
        if snoozed is not None:
            if not isinstance(snoozed, list):
                raise RestorePlanError(f"sessions[{index}].snoozed_thread_ids must be a list")
            missing = [thread_id for thread_id in snoozed if thread_id not in thread_ids]
            if missing:
                raise RestorePlanError(
                    f"sessions[{index}].snoozed_thread_ids contains missing thread ids {missing}"
                )

    return RestorePlan(
        source_username=source_username,
        local_user_id=local_user_id,
        insertion_order=TABLE_ORDER,
        tables=tuple(plans),
    )


def main() -> int:
    """Print a machine-readable dry-run restore plan."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--local-user-id", required=True, type=int)
    parser.add_argument(
        "--next-ids",
        required=True,
        type=Path,
        help="JSON object containing the next available ID for every retained table",
    )
    args = parser.parse_args()

    try:
        document = json.loads(args.file.read_text(encoding="utf-8"))
        next_ids = json.loads(args.next_ids.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise RestorePlanError("export root must be an object")
        if not isinstance(next_ids, dict):
            raise RestorePlanError("next IDs root must be an object")
        plan = build_restore_plan(document, local_user_id=args.local_user_id, next_ids=next_ids)
    except (OSError, json.JSONDecodeError, RestorePlanError) as exc:
        parser.exit(1, f"INVALID: {exc}\n")

    print(json.dumps(asdict(plan), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
