"""Guards for the held #3499 production change set."""

from __future__ import annotations

from pathlib import Path

CHANGESET_DIR = Path("scripts/prod_data_changesets")


def test_changeset_files_forbid_clone_urls_and_backup_tables() -> None:
    """#3499 must not mention Neon clones or create persistent backup tables."""
    sql_blob = "\n".join(
        path.read_text() for path in sorted(CHANGESET_DIR.glob("*.sql"))
    )
    all_blob = "\n".join(
        path.read_text()
        for path in sorted(CHANGESET_DIR.iterdir())
        if path.is_file()
    )
    assert "CLONE_DATABASE_URL" not in all_blob
    assert "CREATE TABLE" not in sql_blob
    assert "prod_changeset_001_ff_issue_backup" not in sql_blob
    assert CHANGESET_DIR.joinpath("stale_blocked_no_live_dep.json").exists() is False
    merge_sql = CHANGESET_DIR.joinpath("001_ff_series_thread_merge.sql").read_text()
    rollback_sql = CHANGESET_DIR.joinpath("001_ff_series_thread_merge_rollback.sql").read_text()
    assert "BETWEEN 115395 AND 115519" in merge_sql
    assert "BETWEEN 115395 AND 115519" in rollback_sql
    assert "intervening write" in rollback_sql
    assert "information_schema.table_constraints" in merge_sql
    hold_sql = CHANGESET_DIR.joinpath("002_adopt_xmen_ff_informational_plans.sql").read_text()
    assert "HELD" in hold_sql
    assert "no plan writes" in hold_sql
