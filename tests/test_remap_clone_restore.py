"""Regression coverage for deterministic retained-export remapping."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from scripts.plan_clone_restore import TABLE_ORDER, build_restore_plan
from scripts.remap_clone_restore import RestoreRemapError, remap_export

JsonObject = dict[str, object]
JsonRows = list[JsonObject]


def _sample_document() -> JsonObject:
    return {
        "source_username": "source-user",
        "user": {"id": 7, "username": "source-user"},
        "threads": [
            {"id": 20, "user_id": 7, "title": "Second"},
            {"id": 10, "user_id": 7, "title": "First"},
        ],
        "issues": [
            {"id": 101, "thread_id": 10, "issue_number": "1"},
            {"id": 102, "thread_id": 20, "issue_number": "2"},
        ],
        "dependencies": [{"id": 301, "thread_id": 20, "depends_on_thread_id": 10}],
        "reading_orders": [{"id": 401, "user_id": 7, "name": "Order"}],
        "reading_order_items": [
            {"id": 501, "reading_order_id": 401, "thread_id": 20, "issue_id": 102}
        ],
        "sessions": [
            {
                "id": 601,
                "user_id": 7,
                "pending_thread_id": 20,
                "snoozed_thread_ids": [10],
            }
        ],
        "events": [
            {
                "id": 701,
                "session_id": 601,
                "thread_id": 20,
                "selected_thread_id": 10,
                "issue_id": 102,
            }
        ],
        "snapshots": [
            {
                "id": 801,
                "session_id": 601,
                "event_id": 701,
                "thread_states": {"10": {"title": "First"}, "_queue_changes": {"20": 2}},
                "session_state": {"pending_thread_id": 20, "snoozed_thread_ids": [10]},
            }
        ],
    }


def _next_ids() -> dict[str, int]:
    return {table: (index + 1) * 1000 for index, table in enumerate(TABLE_ORDER)}


def _object(document: JsonObject, key: str) -> JsonObject:
    value = document[key]
    assert isinstance(value, dict)
    return cast(JsonObject, value)


def _rows(document: JsonObject, key: str) -> JsonRows:
    value = document[key]
    assert isinstance(value, list)
    assert all(isinstance(row, dict) for row in value)
    return cast(JsonRows, value)


def test_remap_export_rewrites_graph_without_mutating_input() -> None:
    """Remap every retained relationship while preserving source evidence."""
    document = _sample_document()
    original = deepcopy(document)
    plan = build_restore_plan(document, local_user_id=42, next_ids=_next_ids())

    result = remap_export(document, plan=plan)

    assert document == original
    assert _object(result, "user")["id"] == 42
    assert [row["id"] for row in _rows(result, "threads")] == [1001, 1000]
    assert {row["user_id"] for row in _rows(result, "threads")} == {42}
    assert _rows(result, "issues") == [
        {"id": 2000, "thread_id": 1000, "issue_number": "1"},
        {"id": 2001, "thread_id": 1001, "issue_number": "2"},
    ]
    assert _rows(result, "dependencies")[0]["thread_id"] == 1001
    assert _rows(result, "dependencies")[0]["depends_on_thread_id"] == 1000
    assert _rows(result, "reading_orders")[0]["user_id"] == 42
    assert _rows(result, "reading_order_items")[0] == {
        "id": 5000,
        "reading_order_id": 4000,
        "thread_id": 1001,
        "issue_id": 2001,
    }
    assert _rows(result, "sessions")[0]["pending_thread_id"] == 1001
    assert _rows(result, "sessions")[0]["snoozed_thread_ids"] == [1000]
    assert _rows(result, "events")[0]["session_id"] == 6000
    assert _rows(result, "events")[0]["selected_thread_id"] == 1000
    assert _rows(result, "snapshots")[0]["thread_states"] == {
        "1000": {"title": "First"},
        "_queue_changes": {"1001": 2},
    }
    assert _rows(result, "snapshots")[0]["session_state"] == {
        "pending_thread_id": 1001,
        "snoozed_thread_ids": [1000],
    }


def test_remap_export_preserves_nullable_references() -> None:
    """Keep nullable references null instead of manufacturing local IDs."""
    document = _sample_document()
    _rows(document, "sessions")[0]["pending_thread_id"] = None
    _rows(document, "sessions")[0]["snoozed_thread_ids"] = None
    _rows(document, "events")[0]["thread_id"] = None
    _rows(document, "snapshots")[0]["thread_states"] = None
    plan = build_restore_plan(document, local_user_id=42, next_ids=_next_ids())

    result = remap_export(document, plan=plan)

    assert _rows(result, "sessions")[0]["pending_thread_id"] is None
    assert _rows(result, "sessions")[0]["snoozed_thread_ids"] is None
    assert _rows(result, "events")[0]["thread_id"] is None
    assert _rows(result, "snapshots")[0]["thread_states"] is None


def test_remap_export_fails_closed_for_missing_reference() -> None:
    """Reject retained rows whose foreign keys are absent from the plan."""
    document = _sample_document()
    _rows(document, "events")[0]["selected_thread_id"] = 999
    plan = build_restore_plan(document, local_user_id=42, next_ids=_next_ids())

    with pytest.raises(RestoreRemapError, match="missing threads id 999"):
        remap_export(document, plan=plan)
