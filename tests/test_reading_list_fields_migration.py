"""Verify inactive Reading List fields on existing PostgreSQL rows."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_inactive_fields_migration_roundtrip(async_db: AsyncSession) -> None:
    """Preserve legacy values, enforce intent choices, and support downgrade."""
    path = Path(__file__).parents[1] / (
        "alembic/versions/c36620000001_add_inactive_reading_list_fields.py"
    )
    spec = importlib.util.spec_from_file_location("reading_list_fields_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def run(conn: Connection) -> None:
        conn.execute(text("CREATE TEMP TABLE custom_cbl_lists (id int PRIMARY KEY) ON COMMIT DROP"))
        conn.execute(
            text("""
            CREATE TEMP TABLE custom_cbl_entries (
                id int PRIMARY KEY, issue_id int, position int,
                is_checkpoint boolean, checkpoint_target_issue_ids json
            ) ON COMMIT DROP
        """)
        )
        conn.execute(text("INSERT INTO custom_cbl_lists VALUES (1)"))
        conn.execute(text("INSERT INTO custom_cbl_entries VALUES (1,101,7,true,'[102]')"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        assert conn.execute(text("SELECT mode FROM custom_cbl_lists")).scalar_one() == "loose"
        assert conn.execute(
            text("""
            SELECT issue_id, position, is_checkpoint, checkpoint_target_issue_ids::text,
                   gate, skipped FROM custom_cbl_entries
        """)
        ).one() == (101, 7, True, "[102]", "none", False)
        for mode in ("strict", "loose"):
            conn.execute(text("UPDATE custom_cbl_lists SET mode=:mode"), {"mode": mode})
        for gate in ("none", "hold", "after_previous"):
            conn.execute(text("UPDATE custom_cbl_entries SET gate=:gate"), {"gate": gate})
        for statement in (
            "UPDATE custom_cbl_lists SET mode='other'",
            "UPDATE custom_cbl_entries SET gate='other'",
            "UPDATE custom_cbl_lists SET mode=NULL",
            "UPDATE custom_cbl_entries SET gate=NULL",
            "UPDATE custom_cbl_entries SET skipped=NULL",
        ):
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(text(statement))
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert conn.execute(
            text("""
            SELECT issue_id, position, is_checkpoint, checkpoint_target_issue_ids::text
            FROM custom_cbl_entries
        """)
        ).one() == (101, 7, True, "[102]")
        conn.execute(text("DROP TABLE custom_cbl_entries"))
        conn.execute(text("DROP TABLE custom_cbl_lists"))

    connection = await async_db.connection()
    await connection.run_sync(run)
