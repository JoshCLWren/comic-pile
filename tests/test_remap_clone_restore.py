from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.plan_clone_restore import TABLE_ORDER, build_restore_plan
from scripts.remap_clone_restore import RestoreRemapError, remap_export


def sample_document() -> dict[str, object]:
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
        "reading_order_items": [{"id": 501, "reading_order_id": 401, "thread_id": 20, "issue_id": 102}],
        "sessions": [{"id": 601, "user_id": 7, "pending_thread_id": 20, "snoozed_thread_ids": [10]}],
        "events": [{"id": 701, "session_id": 601, "thread_id": 20, "selected_thread_id": 10, "issue_id": 102}],
        "snapshots": [{
            "id": 801,
            "session_id": 601,
            "event_id": 701,
            "thread_states": {"10": {"title": "First"}, "_queue_changes": {"20": 2}},
            "session_state": {"pending_thread_id": 20, "snoozed_thread_ids": [10]},
        }],
    }


def next_ids() -> dict[str, int]:
    return {table: (index + 1) * 1000 for index, table in enumerate(TABLE_ORDER)}


def test_remap_export_rewrites_graph_without_mutating_input() -> None:
    document = sample_document()
    original = deepcopy(document)
    plan = build_restore_plan(document, local_user_id=42, next_ids=next_ids())

    result = remap_export(document, plan=plan)

    assert document == original
    assert result["user"]["id"] == 42
    assert [row["id"] for row in result["threads"]] == [1001, 1000]
    assert {row["user_id"] for row in result["threads"]} == {42}
    assert result["issues"] == [
        {"id": 2000, "thread_id": 1000, "issue_number": "1"},
        {"id": 2001, "thread_id": 1001, "issue_number": "2"},
    ]
    assert result["dependencies"][0]["thread_id"] == 1001
    assert result["dependencies"][0]["depends_on_thread_id"] == 1000
    assert result["reading_orders"][0]["user_id"] == 42
    assert result["reading_order_items"][0] == {
        "id": 5000,
        "reading_order_id": 4000,
        "thread_id": 1001,
        "issue_id": 2001,
    }
    assert result["sessions"][0]["pending_thread_id"] == 1001
    assert result["sessions"][0]["snoozed_thread_ids"] == [1000]
    assert result["events"][0]["session_id"] == 6000
    assert result["events"][0]["selected_thread_id"] == 1000
    assert result["snapshots"][0]["thread_states"] == {
        "1000": {"title": "First"},
        "_queue_changes": {"1001": 2},
    }
    assert result["snapshots"][0]["session_state"] == {
        "pending_thread_id": 1001,
        "snoozed_thread_ids": [1000],
    }


def test_remap_export_preserves_nullable_references() -> None:
    document = sample_document()
    document["sessions"][0]["pending_thread_id"] = None
    document["sessions"][0]["snoozed_thread_ids"] = None
    document["events"][0]["thread_id"] = None
    document["snapshots"][0]["thread_states"] = None
    plan = build_restore_plan(document, local_user_id=42, next_ids=next_ids())

    result = remap_export(document, plan=plan)

    assert result["sessions"][0]["pending_thread_id"] is None
    assert result["sessions"][0]["snoozed_thread_ids"] is None
    assert result["events"][0]["thread_id"] is None
    assert result["snapshots"][0]["thread_states"] is None


def test_remap_export_fails_closed_for_missing_reference() -> None:
    document = sample_document()
    document["events"][0]["selected_thread_id"] = 999
    plan = build_restore_plan(document, local_user_id=42, next_ids=next_ids())

    with pytest.raises(RestoreRemapError, match="missing threads id 999"):
        remap_export(document, plan=plan)
