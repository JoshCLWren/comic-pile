"""Unit coverage for the prod-shaped migration fixture generator (issue #3554)."""

from scripts.generate_migration_fixture import _rows_for_columns, build_fixture


def test_rows_are_limited_to_columns_present_at_the_rehearsed_revision() -> None:
    """A column added by a pending migration is omitted at the base revision.

    The deploy rehearsal loads the fixture at the production base revision and
    only then applies pending migrations, so a fixture row that names a not-yet
    existing column would abort the whole deploy. Restricting the row keeps the
    load valid and leaves backfilling to the pending migration.
    """
    rows = [{"id": 1, "username": "reader", "added_later": None}]

    assert _rows_for_columns(rows, {"id", "username"}) == [
        {"id": 1, "username": "reader"}
    ]


def test_rows_are_unchanged_when_every_column_exists() -> None:
    """At head every fixture column exists, so filtering is the identity."""
    fixture = build_fixture()
    threads = fixture["threads"]

    assert _rows_for_columns(threads, set(threads[0])) == threads


def test_rows_handle_a_table_with_no_usable_columns() -> None:
    """A table with no shared columns yields rows that callers can skip."""
    assert _rows_for_columns([{"id": 1}], set()) == [{}]


def test_fixture_covers_the_issue_edge_cases() -> None:
    """The fixture keeps the prod-shaped shapes issue #3554 requires."""
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


def test_fixture_contains_only_synthetic_identities() -> None:
    """No fixture row carries a real email domain or credential."""
    fixture = build_fixture()

    for user in fixture["users"]:
        assert user["email"].endswith("@example.invalid")
        assert user["password_hash"].startswith("synthetic-password-hash-")
