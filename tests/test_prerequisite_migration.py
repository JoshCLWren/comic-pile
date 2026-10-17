"""Add prerequisite metadata without assigning historical reader intent."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def test_provenance_migration_roundtrip(async_db: AsyncSession) -> None:
    """Legacy endpoints/notes survive; converted rows require provenance and class."""
    path = Path(__file__).parents[1] / "alembic/versions/c36690000001_prerequisite_provenance.py"
    spec = importlib.util.spec_from_file_location("prerequisite_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def run(conn: Connection) -> None:
        conn.execute(
            text(
                "CREATE TEMP TABLE dependencies (id int PRIMARY KEY, "
                "source_issue_id int, target_issue_id int, note text) ON COMMIT DROP"
            )
        )
        conn.execute(text("INSERT INTO dependencies VALUES (1,26360,117189,'original source')"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        assert conn.execute(text("SELECT * FROM dependencies")).one() == (
            1,
            26360,
            117189,
            "original source",
            None,
            None,
            None,
        )
        for statement in (
            "UPDATE dependencies SET origin='automatic'",
            "UPDATE dependencies SET classification='Z'",
            "UPDATE dependencies SET origin='converted'",
        ):
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(text(statement))
        conn.execute(
            text(
                "UPDATE dependencies SET origin='converted', classification='D', "
                "provenance='original source; intent unknown'"
            )
        )
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert conn.execute(text("SELECT * FROM dependencies")).one() == (
            1,
            26360,
            117189,
            "original source",
        )
        conn.execute(text("DROP TABLE dependencies"))

    connection = await async_db.connection()
    await connection.run_sync(run)
