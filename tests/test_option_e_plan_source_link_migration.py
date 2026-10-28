"""Execute the Option E Plan-to-List backfill against a real PostgreSQL transaction."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_option_e_backfill_reuses_audited_planetary_and_preserves_other_plans(
    async_db: AsyncSession,
) -> None:
    """No duplicate Planetary list; all other legacy membership retained on replay."""
    path = Path(__file__).parents[1] / (
        "alembic/versions/c42550000001_complete_option_e_source_links.py"
    )
    spec = importlib.util.spec_from_file_location("option_e_source_link_backfill", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def run(conn: Connection) -> None:
        ddl = [
            """CREATE TEMP TABLE continuity_plans (
              id integer PRIMARY KEY, user_id integer, name varchar(200),
              ordering_mode text
            ) ON COMMIT DROP""",
            """CREATE TEMP TABLE reading_plan_issues (
              plan_id integer, issue_id integer, display_position integer,
              occurrence_id text, lane_id text, is_checkpoint boolean
            ) ON COMMIT DROP""",
            """CREATE TEMP TABLE reading_plan_sources (
              plan_id integer, raw_source_path text,
              custom_cbl_list_id integer, recorded_at timestamptz
            ) ON COMMIT DROP""",
            """CREATE TEMP TABLE custom_cbl_lists (
              id serial PRIMARY KEY, user_id integer, name varchar(200),
              mode text, created_at timestamptz, updated_at timestamptz
            ) ON COMMIT DROP""",
            """CREATE TEMP TABLE custom_cbl_entries (
              list_id integer, issue_id integer, position integer,
              gate text, skipped boolean, is_checkpoint boolean,
              created_at timestamptz
            ) ON COMMIT DROP""",
        ]
        for statement in ddl:
            conn.execute(text(statement))
        seeds = [
            """INSERT INTO continuity_plans VALUES
              (29, 1, 'Planetary / Authority', 'strict_sequential'),
              (40, 1, 'Legacy single-lane', 'informational'),
              (41, 1, 'Empty legacy plan', 'informational')""",
            """INSERT INTO custom_cbl_lists (id,user_id,name,mode) VALUES
              (1000018,1,'Planetary / Authority','strict')""",
            """INSERT INTO reading_plan_issues
              (plan_id,issue_id,display_position,occurrence_id,lane_id,is_checkpoint)
            SELECT 29, i, i - 1, i::text, 'main', false
            FROM generate_series(1,144) i""",
            """INSERT INTO custom_cbl_entries
              (list_id,issue_id,position,gate,skipped,is_checkpoint)
            SELECT 1000018, i, i - 1, 'none', false, false
            FROM generate_series(1,145) i""",
            """INSERT INTO reading_plan_issues VALUES
              (40,200,0,'first','main',false),
              (40,201,1,'second','main',true)""",
            """INSERT INTO reading_plan_sources VALUES
              (29,'comicvine:4050-18250',NULL,now())""",
        ]
        for statement in seeds:
            conn.execute(text(statement))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            # Replay must be safe and must not create additional Lists.
            module.upgrade()
        rows = conn.execute(text("""
            SELECT p.id, s.custom_cbl_list_id
            FROM continuity_plans p
            JOIN reading_plan_sources s ON s.plan_id=p.id
            WHERE s.custom_cbl_list_id IS NOT NULL ORDER BY p.id
        """)).all()
        assert len(rows) == 3
        assert rows[0] == (29,1000018)
        assert len({row[1] for row in rows}) == 3
        assert conn.execute(text(
            "SELECT count(*) FROM custom_cbl_lists"
        )).scalar_one() == 3
        assert conn.execute(text(
            "SELECT count(*) FROM custom_cbl_entries WHERE list_id=1000018"
        )).scalar_one() == 145
        created = rows[1][1]
        assert conn.execute(text("""
            SELECT issue_id,position,is_checkpoint FROM custom_cbl_entries
            WHERE list_id=:l ORDER BY position
        """), {"l": created}).all() == [(200,0,False),(201,1,True)]
        assert conn.execute(text("""
            SELECT count(*) FROM reading_plan_sources
            WHERE plan_id=29 AND raw_source_path='comicvine:4050-18250'
        """)).scalar_one() == 1
        for table_name in (
            "custom_cbl_entries", "custom_cbl_lists", "reading_plan_sources",
            "reading_plan_issues", "continuity_plans",
        ):
            conn.execute(text(f"DROP TABLE {table_name}"))

    connection = await async_db.connection()
    await connection.run_sync(run)
