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
    assert "new dependencies reference moved issues" not in rollback_sql
    assert "new reading_plan_issues reference moved issues" not in rollback_sql
    assert "new events reference moved issues" not in rollback_sql
    assert _REF_GUARD_EXCEPTION in merge_sql
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
        for parsed in _quoted_json_all(sql, "rec_refs"):
            assert parsed == recorded["moved_issue_refs"]


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


def _ref_guard_sql(recorded: object, lo: int, hi: int) -> str:
    """Return a DO block that refuses when live refs drift from ``recorded``.

    Args:
        recorded: Baseline JSON object captured at merge time.
        lo: Inclusive low issue id.
        hi: Inclusive high issue id.

    Returns:
        PL/pgSQL DO block matching the rollback drift guard.
    """
    payload = json.dumps(recorded, separators=(",", ":")).replace(":", r"\:")
    return f"""
    DO $guard$
    DECLARE
        recorded_refs jsonb := $rec_refs${payload}$rec_refs$::jsonb;
        live_refs jsonb;
    BEGIN
        SELECT {_moved_issue_refs_sql(lo, hi)} INTO live_refs;
        IF live_refs IS DISTINCT FROM recorded_refs THEN
            RAISE EXCEPTION '{_REF_GUARD_EXCEPTION}: %', live_refs;
        END IF;
    END;
    $guard$;
    """


async def _fetch_moved_issue_refs(db: AsyncSession, lo: int, hi: int) -> object:
    """Load the merge-time reference baseline for one issue-id window.

    Args:
        db: Async database session.
        lo: Inclusive low issue id.
        hi: Inclusive high issue id.

    Returns:
        JSON object with dependency, reading_plan_issues, and events fingerprints.
    """
    row = (await db.execute(text(f"SELECT {_moved_issue_refs_sql(lo, hi)} AS refs"))).one()
    refs = row.refs
    if isinstance(refs, str):
        return json.loads(refs)
    return refs


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
    """Pre-existing deps match the baseline; new, removed, or changed rows refuse."""
    first, second, existing = await _seed_moved_issue_pair(async_db)
    lo = min(first.id, second.id)
    hi = max(first.id, second.id)
    baseline = await _fetch_moved_issue_refs(async_db, lo, hi)
    assert isinstance(baseline, dict)
    assert baseline["dependencies"]["count"] == 1
    assert baseline["reading_plan_issues"]["count"] == 0
    assert baseline["events"]["count"] == 0

    await async_db.execute(text(_ref_guard_sql(baseline, lo, hi)))

    extra = Dependency(
        source_issue_id=second.id,
        target_issue_id=first.id,
        note="cbl-order:source:ff-early-years:2->1",
    )
    async_db.add(extra)
    await async_db.flush()
    with pytest.raises(DBAPIError, match=_REF_GUARD_EXCEPTION):
        async with async_db.begin_nested():
            await async_db.execute(text(_ref_guard_sql(baseline, lo, hi)))
    await async_db.delete(extra)
    await async_db.flush()
    await async_db.execute(text(_ref_guard_sql(baseline, lo, hi)))

    original_note = existing.note
    existing.note = "cbl-order:source:ff-early-years:changed"
    await async_db.flush()
    with pytest.raises(DBAPIError, match=_REF_GUARD_EXCEPTION):
        async with async_db.begin_nested():
            await async_db.execute(text(_ref_guard_sql(baseline, lo, hi)))
    existing.note = original_note
    await async_db.flush()
    await async_db.execute(text(_ref_guard_sql(baseline, lo, hi)))

    extra_event = Event(type="rate", issue_id=first.id, issue_number=first.issue_number)
    async_db.add(extra_event)
    await async_db.flush()
    with pytest.raises(DBAPIError, match=_REF_GUARD_EXCEPTION):
        async with async_db.begin_nested():
            await async_db.execute(text(_ref_guard_sql(baseline, lo, hi)))
    await async_db.delete(extra_event)
    await async_db.flush()
    await async_db.execute(text(_ref_guard_sql(baseline, lo, hi)))

    await async_db.delete(existing)
    await async_db.flush()
    with pytest.raises(DBAPIError, match=_REF_GUARD_EXCEPTION):
        async with async_db.begin_nested():
            await async_db.execute(text(_ref_guard_sql(baseline, lo, hi)))
