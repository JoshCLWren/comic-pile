#!/usr/bin/env python3
"""Remap a validated production clone export for safe local insertion."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Final

from scripts.plan_clone_restore import RestorePlan, RestorePlanError, build_restore_plan

REFERENCE_FIELDS: Final[dict[str, dict[str, str]]] = {
    "issues": {"thread_id": "threads"},
    "dependencies": {
        "thread_id": "threads",
        "depends_on_thread_id": "threads",
        "issue_id": "issues",
        "depends_on_issue_id": "issues",
    },
    "reading_order_items": {
        "reading_order_id": "reading_orders",
        "thread_id": "threads",
        "issue_id": "issues",
    },
    "events": {
        "session_id": "sessions",
        "thread_id": "threads",
        "selected_thread_id": "threads",
        "acted_on_thread_id": "threads",
        "issue_id": "issues",
    },
    "snapshots": {
        "session_id": "sessions",
        "event_id": "events",
    },
}
USER_OWNED_TABLES: Final = {"threads", "reading_orders", "sessions"}


class RestoreRemapError(RestorePlanError):
    """Raised when an export cannot be remapped without losing references."""


def _plan_maps(plan: RestorePlan) -> dict[str, dict[int, int]]:
    return {table.table: table.id_map for table in plan.tables}


def _remap_reference(
    value: object,
    *,
    table: str,
    field: str,
    target_table: str,
    id_maps: Mapping[str, Mapping[int, int]],
) -> object:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise RestoreRemapError(f"{table}.{field} must be an integer or null")
    try:
        return id_maps[target_table][value]
    except KeyError as exc:
        raise RestoreRemapError(
            f"{table}.{field} references missing {target_table} id {value}"
        ) from exc


def _remap_thread_state_keys(
    value: object,
    *,
    id_maps: Mapping[str, Mapping[int, int]],
) -> object:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RestoreRemapError("snapshots.thread_states must be an object or null")

    remapped: dict[str, object] = {}
    metadata_keys = {"_snapshot_version", "_queue_changes", "_blocked_changes"}
    for key, nested in value.items():
        if key in metadata_keys:
            if key in {"_queue_changes", "_blocked_changes"} and nested is not None:
                if not isinstance(nested, dict):
                    raise RestoreRemapError(f"snapshots.thread_states.{key} must be an object")
                remapped[key] = {
                    str(
                        _remap_reference(
                            int(thread_id),
                            table="snapshots.thread_states",
                            field=key,
                            target_table="threads",
                            id_maps=id_maps,
                        )
                    ): state
                    for thread_id, state in nested.items()
                }
            else:
                remapped[key] = nested
            continue

        try:
            source_thread_id = int(key)
        except (TypeError, ValueError) as exc:
            raise RestoreRemapError(
                f"snapshots.thread_states contains unsupported key {key!r}"
            ) from exc
        local_thread_id = _remap_reference(
            source_thread_id,
            table="snapshots.thread_states",
            field="thread_id",
            target_table="threads",
            id_maps=id_maps,
        )
        remapped[str(local_thread_id)] = nested
    return remapped


def remap_export(
    document: Mapping[str, object],
    *,
    plan: RestorePlan,
) -> dict[str, object]:
    """Return a deep-copied export with local IDs and references applied."""
    id_maps = _plan_maps(plan)
    remapped = deepcopy(dict(document))
    source_user = remapped.get("user")
    if not isinstance(source_user, dict):
        raise RestoreRemapError("user must be an object")
    source_user["id"] = plan.local_user_id

    for table_plan in plan.tables:
        table = table_plan.table
        rows = remapped.get(table)
        if not isinstance(rows, list):
            raise RestoreRemapError(f"{table} must be a list")

        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise RestoreRemapError(f"{table}[{index}] must be an object")
            source_id = row.get("id")
            if not isinstance(source_id, int) or isinstance(source_id, bool):
                raise RestoreRemapError(f"{table}[{index}].id must be an integer")
            try:
                row["id"] = id_maps[table][source_id]
            except KeyError as exc:
                raise RestoreRemapError(
                    f"restore plan has no mapping for {table} id {source_id}"
                ) from exc

            if table in USER_OWNED_TABLES:
                row["user_id"] = plan.local_user_id

            for field, target_table in REFERENCE_FIELDS.get(table, {}).items():
                if field in row:
                    row[field] = _remap_reference(
                        row[field],
                        table=table,
                        field=field,
                        target_table=target_table,
                        id_maps=id_maps,
                    )

            if table == "sessions":
                if "pending_thread_id" in row:
                    row["pending_thread_id"] = _remap_reference(
                        row["pending_thread_id"],
                        table=table,
                        field="pending_thread_id",
                        target_table="threads",
                        id_maps=id_maps,
                    )
                snoozed = row.get("snoozed_thread_ids")
                if snoozed is not None:
                    if not isinstance(snoozed, list):
                        raise RestoreRemapError(
                            "sessions.snoozed_thread_ids must be a list or null"
                        )
                    row["snoozed_thread_ids"] = [
                        _remap_reference(
                            thread_id,
                            table=table,
                            field="snoozed_thread_ids",
                            target_table="threads",
                            id_maps=id_maps,
                        )
                        for thread_id in snoozed
                    ]

            if table == "snapshots":
                row["thread_states"] = _remap_thread_state_keys(
                    row.get("thread_states"), id_maps=id_maps
                )
                session_state = row.get("session_state")
                if isinstance(session_state, dict):
                    pending = session_state.get("pending_thread_id")
                    if pending is not None:
                        session_state["pending_thread_id"] = _remap_reference(
                            pending,
                            table="snapshots.session_state",
                            field="pending_thread_id",
                            target_table="threads",
                            id_maps=id_maps,
                        )
                    snoozed = session_state.get("snoozed_thread_ids")
                    if snoozed is not None:
                        if not isinstance(snoozed, list):
                            raise RestoreRemapError(
                                "snapshots.session_state.snoozed_thread_ids must be a list"
                            )
                        session_state["snoozed_thread_ids"] = [
                            _remap_reference(
                                thread_id,
                                table="snapshots.session_state",
                                field="snoozed_thread_ids",
                                target_table="threads",
                                id_maps=id_maps,
                            )
                            for thread_id in snoozed
                        ]

    remapped["restore_plan"] = asdict(plan)
    return remapped


def main() -> int:
    """Remap a clone-export document and write the local insertion artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--local-user-id", required=True, type=int)
    parser.add_argument("--next-ids", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        document = json.loads(args.file.read_text(encoding="utf-8"))
        next_ids = json.loads(args.next_ids.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise RestoreRemapError("export root must be an object")
        if not isinstance(next_ids, dict):
            raise RestoreRemapError("next IDs root must be an object")
        plan = build_restore_plan(
            document,
            local_user_id=args.local_user_id,
            next_ids=next_ids,
        )
        output = remap_export(document, plan=plan)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, RestorePlanError) as exc:
        parser.exit(1, f"INVALID: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
