"""Tests for deterministic clone restore planning."""

from scripts.plan_clone_restore import TABLE_ORDER, RestorePlanError, build_restore_plan


def _document() -> dict[str, object]:
    """Return a minimal valid retained-data export."""
    return {
        "source_username": "Josh",
        "user": {"id": 7},
        "threads": [{"id": 20, "user_id": 7}, {"id": 10, "user_id": 7}],
        "issues": [{"id": 30, "thread_id": 10}],
        "dependencies": [],
        "reading_orders": [{"id": 40, "user_id": 7}],
        "reading_order_items": [],
        "sessions": [{"id": 50, "user_id": 7, "snoozed_thread_ids": [20]}],
        "events": [],
        "snapshots": [],
    }


def _next_ids() -> dict[str, int]:
    """Return deterministic local sequence starts."""
    return {table: 1000 + index * 100 for index, table in enumerate(TABLE_ORDER)}


def test_build_restore_plan_sorts_source_ids_and_allocates_contiguous_local_ids() -> None:
    """Source row order must not change the resulting ID map."""
    plan = build_restore_plan(_document(), local_user_id=3, next_ids=_next_ids())

    thread_plan = plan.tables[0]
    assert plan.source_username == "Josh"
    assert plan.local_user_id == 3
    assert plan.insertion_order == TABLE_ORDER
    assert thread_plan.id_map == {10: 1000, 20: 1001}
    assert thread_plan.first_local_id == 1000
    assert thread_plan.last_local_id == 1001


def test_build_restore_plan_keeps_empty_tables_explicit() -> None:
    """Dry-run output should preserve every insertion stage even when empty."""
    plan = build_restore_plan(_document(), local_user_id=3, next_ids=_next_ids())

    dependency_plan = next(item for item in plan.tables if item.table == "dependencies")
    assert dependency_plan.source_count == 0
    assert dependency_plan.first_local_id is None
    assert dependency_plan.last_local_id is None
    assert dependency_plan.id_map == {}


def test_build_restore_plan_rejects_cross_user_records() -> None:
    """A restore plan must never silently adopt another user's retained rows."""
    document = _document()
    document["reading_orders"] = [{"id": 40, "user_id": 99}]

    try:
        build_restore_plan(document, local_user_id=3, next_ids=_next_ids())
    except RestorePlanError as exc:
        assert "reading_orders[0].user_id" in str(exc)
    else:
        raise AssertionError("cross-user record was accepted")


def test_build_restore_plan_rejects_missing_snoozed_thread() -> None:
    """Session thread references must be resolvable before database mutation."""
    document = _document()
    document["sessions"] = [{"id": 50, "user_id": 7, "snoozed_thread_ids": [999]}]

    try:
        build_restore_plan(document, local_user_id=3, next_ids=_next_ids())
    except RestorePlanError as exc:
        assert "missing thread ids [999]" in str(exc)
    else:
        raise AssertionError("missing snoozed thread was accepted")


def test_build_restore_plan_rejects_duplicate_ids() -> None:
    """Duplicate source IDs would make remapping ambiguous and must fail closed."""
    document = _document()
    document["issues"] = [{"id": 30, "thread_id": 10}, {"id": 30, "thread_id": 20}]

    try:
        build_restore_plan(document, local_user_id=3, next_ids=_next_ids())
    except RestorePlanError as exc:
        assert "issues contains duplicate id 30" in str(exc)
    else:
        raise AssertionError("duplicate IDs were accepted")
