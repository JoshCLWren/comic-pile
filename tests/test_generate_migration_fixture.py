"""Unit coverage for the prod-shaped migration fixture generator (issue #3554)."""

from sqlalchemy import Column, Integer, MetaData, String, Table

from scripts.generate_migration_fixture import (
    FIXTURE_FILLER_THREADS,
    FIXTURE_ISSUES_PER_FILLER_THREAD,
    _rehearsal_table,
    _rows_for_columns,
    build_fixture,
)


def test_rows_are_limited_to_columns_present_at_the_rehearsed_revision() -> None:
    """A pending migration's new column is omitted from a base-schema insert."""
    rows = [{"id": 1, "username": "reader", "added_later": None}]

    assert _rows_for_columns(rows, {"id", "username"}) == [
        {"id": 1, "username": "reader"}
    ]


def test_rows_are_unchanged_when_every_column_exists() -> None:
    """At head, filtering the explicit fixture values is the identity."""
    fixture = build_fixture()
    threads = fixture["threads"]

    assert _rows_for_columns(threads, set(threads[0])) == threads


def test_rehearsal_table_cannot_default_a_head_only_column_into_base_insert() -> None:
    """A model default must not re-add a column absent at the base revision."""
    model_table = Table(
        "rehearsal_demo",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("name", String, default="synthetic"),
        Column("added_later", String, default="head-only-default"),
    )

    rehearsal_table = _rehearsal_table(model_table, {"id", "name"})

    assert set(rehearsal_table.columns) == {"id", "name"}
    assert rehearsal_table.columns["name"].default is not None
    assert "added_later" not in rehearsal_table.columns


def test_fixture_covers_the_issue_edge_cases() -> None:
    """The fixture retains every prod-shaped edge case named by the issue."""
    fixture = build_fixture()

    assert len(fixture["users"]) >= 2
    assert fixture["dependencies"]
    assert any(
        row["note"].startswith("cbl-order:")
        for row in fixture["dependencies"]
        if row["note"]
    )
    plan = fixture["continuity_plans"][0]
    assert plan["nodes_json"]
    assert plan["lanes_json"]
    assert fixture["cbl_adoption_receipts"]
    assert any(row["is_blocked"] for row in fixture["threads"])
    assert any(row["snoozed_thread_ids"] for row in fixture["sessions"])
    assert any(row["password_changed_at"] is None for row in fixture["users"])
    assert any(row["read_at"] is None for row in fixture["issues"])
    assert any(row["last_activity_at"] is None for row in fixture["threads"])


def test_fixture_carries_a_bounded_representative_volume_tier() -> None:
    """Data migrations run against hundreds of synthetic issues, not four rows."""
    fixture = build_fixture()

    assert len(fixture["threads"]) == 3 + FIXTURE_FILLER_THREADS
    assert len(fixture["issues"]) == (
        4 + FIXTURE_FILLER_THREADS * FIXTURE_ISSUES_PER_FILLER_THREAD
    )
    assert len({row["id"] for row in fixture["threads"]}) == len(fixture["threads"])
    assert len({row["id"] for row in fixture["issues"]}) == len(fixture["issues"])


def test_fixture_contains_only_synthetic_identities() -> None:
    """No fixture row carries a real email domain or credential."""
    fixture = build_fixture()

    for user in fixture["users"]:
        assert user["email"].endswith("@example.invalid")
        assert user["password_hash"].startswith("synthetic-password-hash-")
