"""Execute the real checkpoint migration against legacy source-list flags."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_migration_freezes_source_successors_and_clears_terminal_flags(
    async_db: AsyncSession,
) -> None:
    """Backfill within each list, without compiling prerequisites or choosing plan neighbors."""
    path = (
        Path(__file__).parents[1] / "alembic/versions/c36420000001_custom_cbl_checkpoint_targets.py"
    )
    spec = importlib.util.spec_from_file_location("custom_cbl_checkpoint_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def run(conn: Connection) -> None:
        conn.execute(
            text("""
            CREATE TEMP TABLE custom_cbl_entries (
                id int PRIMARY KEY, list_id int, issue_id int, position int, is_checkpoint boolean
            ) ON COMMIT DROP
        """)
        )
        conn.execute(
            text("""
            INSERT INTO custom_cbl_entries VALUES
            (1,10,100,0,true),(2,10,101,1,false),(3,10,102,2,true),
            (4,20,200,0,true),(5,20,201,1,false)
        """)
        )
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        rows = conn.execute(
            text("""
            SELECT id, is_checkpoint, checkpoint_target_issue_ids::text
            FROM custom_cbl_entries ORDER BY id
        """)
        ).all()
        assert rows == [
            (1, True, "[101]"),
            (2, False, "[]"),
            (3, False, "[]"),
            (4, True, "[201]"),
            (5, False, "[]"),
        ]
        conn.execute(text("DROP TABLE custom_cbl_entries"))

    connection = await async_db.connection()
    await connection.run_sync(run)
