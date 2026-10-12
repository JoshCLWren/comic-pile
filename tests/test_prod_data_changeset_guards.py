"""Guards for the held #3499 production change set."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.event import Event
from app.models.issue import Issue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async

CHANGESET_DIR = Path("scripts/prod_data_changesets")
RECORDED_PATH = CHANGESET_DIR.joinpath("001_ff_series_thread_merge_recorded.json")
_MOVED_ISSUE_LO = 115395
_MOVED_ISSUE_HI = 115519
_REF_GUARD_EXCEPTION = "moved-issue references drifted from merge baseline"
_RECEIPT_TABLE = "prod_changeset_001_ff_moved_refs_receipt"
_RECEIPT_CHANGESET_ID = "001_ff_series_thread_merge"
_PREFLIGHT_DEP_COUNT = 23625


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
    assert "prod_changeset_001_ff_issue_backup" not in sql_blob
    assert sql_blob.count("CREATE TABLE") == 1
    assert "CREATE TABLE IF NOT EXISTS prod_changeset_001_ff_moved_refs_receipt" in sql_blob
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
    assert "new dependencies reference moved issues" not in rollback_sql
    assert "new reading_plan_issues reference moved issues" not in rollback_sql
    assert "new events reference moved issues" not in rollback_sql
    assert _REF_GUARD_EXCEPTION in rollback_sql
    assert recorded["moved_issue_refs"]["dependencies"]["count"] == 23625
    assert f"BETWEEN {_MOVED_ISSUE_LO} AND {_MOVED_ISSUE_HI}" in merge_sql
    assert f"BETWEEN {_MOVED_ISSUE_LO} AND {_MOVED_ISSUE_HI}" in rollback_sql
    for sql in (merge_sql, rollback_sql):
        assert "SET LOCAL TimeZone = 'UTC'" in sql
        for parsed in _quoted_json_all(sql, "rec_split"):
            assert parsed == recorded["split_thread"]
        for parsed in _quoted_json_all(sql, "rec_mapping"):
            assert parsed == recorded["mapping"]
        for parsed in _quoted_json_all(sql, "rec_canonical"):
            assert parsed == recorded["canonical_thread"]
        assert "$rec_refs$" not in sql
        assert "51cab31505d01e2f1be31a7e2a45761f" not in sql


def test_ff_merge_persists_live_refs_receipt_that_rollback_consumes() -> None:
    """Rollback baseline is the merge-time receipt, not the preflight constant."""
    merge_sql = CHANGESET_DIR.joinpath("001_ff_series_thread_merge.sql").read_text()
    rollback_sql = CHANGESET_DIR.joinpath("001_ff_series_thread_merge_rollback.sql").read_text()
    recorded = json.loads(RECORDED_PATH.read_text())
    assert recorded["moved_issue_refs"]["dependencies"]["count"] == _PREFLIGHT_DEP_COUNT
    assert f"CREATE TABLE IF NOT EXISTS {_RECEIPT_TABLE}" in merge_sql
    assert f"INSERT INTO {_RECEIPT_TABLE}" in merge_sql
    assert "live_refs" in merge_sql
    persist_idx = merge_sql.index(f"INSERT INTO {_RECEIPT_TABLE}")
    assert "live_refs" in merge_sql[persist_idx : persist_idx + 400]
    assert "recorded_refs" not in merge_sql[persist_idx : persist_idx + 400]
    assert f"FROM {_RECEIPT_TABLE}" in rollback_sql
    assert f"changeset_id = '{_RECEIPT_CHANGESET_ID}'" in rollback_sql
    assert "missing merge-time moved-refs receipt" in rollback_sql
    assert merge_sql.find("FOR UPDATE") < merge_sql.find("INSERT INTO prod_changeset_001_ff_moved_refs_receipt")


def test_held_sql_is_not_wired_into_deploy_or_migrations() -> None:
    """Merging the compiler does not authorize or auto-run 001/002 SQL."""
    workflow_blob = "\n".join(
        path.read_text() for path in Path(".github/workflows").glob("*.yml")
    )
    alembic_blob = "\n".join(
        path.read_text()
        for path in Path("alembic").rglob("*.py")
        if path.is_file()
    )
    assert "001_ff_series_thread_merge.sql" not in workflow_blob
    assert "001_ff_series_thread_merge.sql" not in alembic_blob
    assert "002_adopt_xmen_ff_informational_plans.sql" not in workflow_blob
    assert "002_adopt_xmen_ff_informational_plans.sql" not in alembic_blob


def test_forecast_sql_uses_roll_queue_position_predicate() -> None:
    """Harvy nit: forecast population matches Roll's queue_position >= 1."""
    forecast_sql = CHANGESET_DIR.joinpath("forecast_roll_eligibility.sql").read_text()
    forecast_py = Path("app/services/roll_cutover_forecast.py").read_text()
    assert "queue_position >= 1" in forecast_sql
    assert "queue_position IS NOT NULL" not in forecast_sql
    assert "queue_position >= 1" in forecast_py
    assert "queue_position IS NOT NULL" not in forecast_py


def _moved_issue_refs_sql(lo: int, hi: int) -> str:
    """Return the merge/rollback moved-issue reference fingerprint query.

    Args:
        lo: Inclusive low issue id.
        hi: Inclusive high issue id.

    Returns:
        SQL expression that builds the baseline JSON object.
    """
    return f"""
        jsonb_build_object(
            'dependencies', (
                SELECT jsonb_build_object(
                    'count', COUNT(*)::bigint,
                    'ids_md5', md5(COALESCE(string_agg(id::text, ',' ORDER BY id), '')),
                    'fingerprint_md5', md5(COALESCE(string_agg(
                        concat_ws(
                            CHR(31),
                            id::text,
                            source_issue_id::text,
                            target_issue_id::text,
                            COALESCE(note, '')
                        ),
                        CHR(10) ORDER BY id
                    ), ''))
                )
                FROM dependencies
                WHERE source_issue_id BETWEEN {lo} AND {hi}
                   OR target_issue_id BETWEEN {lo} AND {hi}
            ),
            'reading_plan_issues', (
                SELECT jsonb_build_object(
                    'count', COUNT(*)::bigint,
                    'ids_md5', md5(COALESCE(string_agg(
                        plan_id::text || ':' || occurrence_id,
                        ',' ORDER BY plan_id, occurrence_id
                    ), '')),
                    'fingerprint_md5', md5(COALESCE(string_agg(
                        concat_ws(
                            CHR(31),
                            plan_id::text,
                            occurrence_id,
                            issue_id::text,
                            display_position::text
                        ),
                        CHR(10) ORDER BY plan_id, occurrence_id
                    ), ''))
                )
                FROM reading_plan_issues
                WHERE issue_id BETWEEN {lo} AND {hi}
            ),
            'events', (
                SELECT jsonb_build_object(
                    'count', COUNT(*)::bigint,
                    'ids_md5', md5(COALESCE(string_agg(id::text, ',' ORDER BY id), '')),
                    'fingerprint_md5', md5(COALESCE(string_agg(
                        concat_ws(
                            CHR(31),
                            id::text,
                            type,
                            COALESCE(issue_id::text, ''),
                            COALESCE(issue_number, '')
                        ),
                        CHR(10) ORDER BY id
                    ), ''))
                )
                FROM events
                WHERE issue_id BETWEEN {lo} AND {hi}
            )
        )
    """


def _receipt_ddl() -> str:
    """Return the merge script's one-row receipt table DDL."""
    return f"""
    CREATE TABLE IF NOT EXISTS {_RECEIPT_TABLE} (
        changeset_id text PRIMARY KEY,
        captured_at timestamptz NOT NULL,
        moved_refs jsonb NOT NULL
    )
    """


def _persist_live_refs_sql(lo: int, hi: int) -> str:
    """Return the merge script's persist statement for one issue-id window.

    Args:
        lo: Inclusive low issue id.
        hi: Inclusive high issue id.

    Returns:
        SQL that writes the locked live fingerprint into the merge receipt.
    """
    return f"""
    INSERT INTO {_RECEIPT_TABLE} (
        changeset_id,
        captured_at,
        moved_refs
    ) VALUES (
        '{_RECEIPT_CHANGESET_ID}',
        clock_timestamp(),
        {_moved_issue_refs_sql(lo, hi)}
    )
    ON CONFLICT (changeset_id) DO UPDATE
    SET captured_at = EXCLUDED.captured_at,
        moved_refs = EXCLUDED.moved_refs
    """


def _rollback_consume_guard_sql(lo: int, hi: int) -> str:
    """Return the rollback script's receipt-consuming drift guard.

    Args:
        lo: Inclusive low issue id.
        hi: Inclusive high issue id.

    Returns:
        PL/pgSQL DO block matching the rollback receipt consume path.
    """
    return f"""
    DO $guard$
    DECLARE
        recorded_refs jsonb;
        live_refs jsonb;
    BEGIN
        IF to_regclass('public.{_RECEIPT_TABLE}') IS NULL THEN
            RAISE EXCEPTION 'missing merge-time moved-refs receipt table; refuse rollback';
        END IF;
        SELECT moved_refs INTO recorded_refs
        FROM {_RECEIPT_TABLE}
        WHERE changeset_id = '{_RECEIPT_CHANGESET_ID}';
        IF recorded_refs IS NULL THEN
            RAISE EXCEPTION 'missing merge-time moved-refs receipt; refuse rollback';
        END IF;
        SELECT {_moved_issue_refs_sql(lo, hi)} INTO live_refs;
        IF live_refs IS DISTINCT FROM recorded_refs THEN
            RAISE EXCEPTION '{_REF_GUARD_EXCEPTION}: %', live_refs;
        END IF;
    END;
    $guard$;
    """


async def _seed_moved_issue_pair(db: AsyncSession) -> tuple[Issue, Issue, Dependency]:
    """Create two consecutive issues and one pre-existing cbl-order dependency.

    Args:
        db: Async database session.

    Returns:
        The two issues and the recorded dependency between them.
    """
    user = await get_or_create_user_async(db)
    thread = Thread(
        title="FF rollback baseline",
        format="comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    first = Issue(
        thread_id=thread.id,
        issue_number="103",
        position=1,
        status="unread",
    )
    db.add(first)
    await db.flush()
    second = Issue(
        thread_id=thread.id,
        issue_number="104",
        position=2,
        status="unread",
    )
    db.add(second)
    await db.flush()
    existing = Dependency(
        source_issue_id=first.id,
        target_issue_id=second.id,
        note="cbl-order:source:ff-early-years:1->2",
    )
    db.add(existing)
    await db.flush()
    return first, second, existing


@pytest.mark.asyncio
async def test_ff_rollback_ref_baseline_allows_preexisting_deps_and_refuses_drift(
    async_db: AsyncSession,
) -> None:
    """Merge persists the live fingerprint; rollback consumes that receipt."""
    first, second, existing = await _seed_moved_issue_pair(async_db)
    lo = min(first.id, second.id)
    hi = max(first.id, second.id)
    merge_sql = CHANGESET_DIR.joinpath("001_ff_series_thread_merge.sql").read_text()
    rollback_sql = CHANGESET_DIR.joinpath("001_ff_series_thread_merge_rollback.sql").read_text()
    assert f"CREATE TABLE IF NOT EXISTS {_RECEIPT_TABLE}" in merge_sql
    assert "INSERT INTO prod_changeset_001_ff_moved_refs_receipt" in merge_sql
    assert "SELECT moved_refs INTO recorded_refs" in rollback_sql

    await async_db.execute(text(_receipt_ddl()))
    await async_db.execute(text(_persist_live_refs_sql(lo, hi)))
    stored = (
        await async_db.execute(
            text(f"SELECT moved_refs FROM {_RECEIPT_TABLE} WHERE changeset_id = :cid"),
            {"cid": _RECEIPT_CHANGESET_ID},
        )
    ).scalar_one()
    if isinstance(stored, str):
        stored = json.loads(stored)
    assert stored["dependencies"]["count"] == 1
    assert stored["dependencies"]["count"] != _PREFLIGHT_DEP_COUNT
    assert stored["reading_plan_issues"]["count"] == 0
    assert stored["events"]["count"] == 0

    await async_db.execute(text(_rollback_consume_guard_sql(lo, hi)))

    extra = Dependency(
        source_issue_id=second.id,
        target_issue_id=first.id,
        note="cbl-order:source:ff-early-years:2->1",
    )
    async_db.add(extra)
    await async_db.flush()
    with pytest.raises(DBAPIError, match=_REF_GUARD_EXCEPTION):
        async with async_db.begin_nested():
            await async_db.execute(text(_rollback_consume_guard_sql(lo, hi)))
    await async_db.delete(extra)
    await async_db.flush()
    await async_db.execute(text(_rollback_consume_guard_sql(lo, hi)))

    original_note = existing.note
    existing.note = "cbl-order:source:ff-early-years:changed"
    await async_db.flush()
    with pytest.raises(DBAPIError, match=_REF_GUARD_EXCEPTION):
        async with async_db.begin_nested():
            await async_db.execute(text(_rollback_consume_guard_sql(lo, hi)))
    existing.note = original_note
    await async_db.flush()
    await async_db.execute(text(_rollback_consume_guard_sql(lo, hi)))

    extra_event = Event(type="rate", issue_id=first.id, issue_number=first.issue_number)
    async_db.add(extra_event)
    await async_db.flush()
    with pytest.raises(DBAPIError, match=_REF_GUARD_EXCEPTION):
        async with async_db.begin_nested():
            await async_db.execute(text(_rollback_consume_guard_sql(lo, hi)))
    await async_db.delete(extra_event)
    await async_db.flush()
    await async_db.execute(text(_rollback_consume_guard_sql(lo, hi)))

    recorded = json.loads(RECORDED_PATH.read_text())
    await async_db.execute(
        text(
            f"UPDATE {_RECEIPT_TABLE} SET moved_refs = CAST(:refs AS jsonb) "
            f"WHERE changeset_id = :cid"
        ),
        {"refs": json.dumps(recorded["moved_issue_refs"]), "cid": _RECEIPT_CHANGESET_ID},
    )
    with pytest.raises(DBAPIError, match=_REF_GUARD_EXCEPTION):
        async with async_db.begin_nested():
            await async_db.execute(text(_rollback_consume_guard_sql(lo, hi)))
    await async_db.execute(text(_persist_live_refs_sql(lo, hi)))
    await async_db.execute(text(_rollback_consume_guard_sql(lo, hi)))

    await async_db.delete(existing)
    await async_db.flush()
    with pytest.raises(DBAPIError, match=_REF_GUARD_EXCEPTION):
        async with async_db.begin_nested():
            await async_db.execute(text(_rollback_consume_guard_sql(lo, hi)))
