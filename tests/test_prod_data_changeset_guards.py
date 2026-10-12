"""Guards for the held #3499 production change set."""

from __future__ import annotations

import json
import re
from pathlib import Path

CHANGESET_DIR = Path("scripts/prod_data_changesets")
RECORDED_PATH = CHANGESET_DIR.joinpath("001_ff_series_thread_merge_recorded.json")


def _quoted_json_all(sql: str, tag: str) -> list[object]:
    """Parse every dollar-quoted JSON receipt with ``tag`` in a change-set script.

    Args:
        sql: Change-set SQL text.
        tag: Dollar-quote tag without the surrounding ``$`` markers.

    Returns:
        Parsed JSON values in appearance order.
    """
    matches = re.findall(rf"\${tag}\$(.*?)\${tag}\$", sql, re.S)
    assert matches, f"missing ${tag}$ receipt in SQL"
    return [json.loads(blob) for blob in matches]


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
    hold_sql = CHANGESET_DIR.joinpath("002_adopt_xmen_ff_informational_plans.sql").read_text()
    assert "HELD" in hold_sql
    assert "no plan writes" in hold_sql


def test_ff_merge_locks_before_guards_and_covers_polymorphic_thread_refs() -> None:
    """Harvy medium gaps: FOR UPDATE first, pg_constraint FKs, polymorphic thread refs."""
    merge_sql = CHANGESET_DIR.joinpath("001_ff_series_thread_merge.sql").read_text()
    assert merge_sql.find("FOR UPDATE") < merge_sql.find("RAISE EXCEPTION")
    assert "FROM threads WHERE id IN (3166, 18560)" in merge_sql
    assert "FOR UPDATE" in merge_sql
    assert "pg_constraint" in merge_sql
    assert "information_schema.table_constraints" not in merge_sql
    assert "lower(source_type) = 'thread'" in merge_sql
    assert "lower(target_type) = 'thread'" in merge_sql
    assert "tag_assignments" in merge_sql
    assert "node->>'node_type'" in merge_sql
    assert "convergence_targets" in merge_sql


def test_ff_rollback_restores_from_recorded_json_not_hardcoded_columns() -> None:
    """Rollback populates 18560/378 from the recorded receipt and asserts equality."""
    recorded = json.loads(RECORDED_PATH.read_text())
    merge_sql = CHANGESET_DIR.joinpath("001_ff_series_thread_merge.sql").read_text()
    rollback_sql = CHANGESET_DIR.joinpath("001_ff_series_thread_merge_rollback.sql").read_text()
    assert recorded["split_thread"]["id"] == 18560
    assert recorded["mapping"]["id"] == 378
    assert recorded["canonical_thread"]["reading_progress"] == "in_progress"
    assert "jsonb_populate_record" in rollback_sql
    assert "INSERT INTO threads (" not in rollback_sql
    assert "INSERT INTO thread_external_series_mappings (" not in rollback_sql
    assert "row_to_json" in merge_sql
    assert "row_to_json" in rollback_sql
    assert "reading_progress = 'in_progress'" not in rollback_sql
    assert "new dependencies reference moved issues" in rollback_sql
    assert "new reading_plan_issues reference moved issues" in rollback_sql
    assert "new events reference moved issues" in rollback_sql
    for sql in (merge_sql, rollback_sql):
        for parsed in _quoted_json_all(sql, "rec_split"):
            assert parsed == recorded["split_thread"]
        for parsed in _quoted_json_all(sql, "rec_mapping"):
            assert parsed == recorded["mapping"]
        for parsed in _quoted_json_all(sql, "rec_canonical"):
            assert parsed == recorded["canonical_thread"]


def test_forecast_sql_uses_roll_queue_position_predicate() -> None:
    """Harvy nit: forecast population matches Roll's queue_position >= 1."""
    forecast_sql = CHANGESET_DIR.joinpath("forecast_roll_eligibility.sql").read_text()
    forecast_py = Path("app/services/roll_cutover_forecast.py").read_text()
    assert "queue_position >= 1" in forecast_sql
    assert "queue_position IS NOT NULL" not in forecast_sql
    assert "queue_position >= 1" in forecast_py
    assert "queue_position IS NOT NULL" not in forecast_py
