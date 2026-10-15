"""PostgreSQL migration and graph regression for Option E collection exclusions."""

import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _migration_path() -> Path:
    """Return the migration script belonging to the Option E exclusion feature."""
    return (
        Path(__file__).parents[1]
        / "alembic/versions/c36630000001_collection_exclusions.py"
    )


def test_collection_exclusion_migration_is_single_head() -> None:
    """The new migration extends #3662, without a competing Alembic head."""
    root = Path(__file__).parents[1]
    cfg = Config(str(root / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["c36630000001"]
    current = script.get_revision("c36630000001")
    assert current is not None
    assert current.down_revision == "c36620000001"


@pytest.mark.asyncio
async def test_collection_exclusion_migration_roundtrip_postgres(
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """Upgrade, enforce constraints/indexes and downgrade in PostgreSQL."""
    spec = importlib.util.spec_from_file_location("exclusion_migration", _migration_path())
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def verify(conn: Connection) -> None:
        # pg_temp keeps these migration tables separate from Base.metadata.create_all.
        conn.execute(text("SET LOCAL search_path TO pg_temp, public"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()

        conn.execute(text("""
            INSERT INTO collection_exclusions
                (id, user_id, provider, external_volume_id, created_at)
            VALUES (1, 1, 'comicvine', '4050-10', now())
        """))
        conn.execute(text("""
            INSERT INTO collection_exclusions (id, user_id, thread_id, created_at)
            VALUES (2, 1, 987654, now())
        """))
        conn.execute(text("""
            INSERT INTO collection_exclusions (id, user_id, issue_id, created_at)
            VALUES (3, 1, 987655, now())
        """))
        for statement in (
            "INSERT INTO collection_exclusions (id,user_id,created_at) VALUES (4,1,now())",
            "INSERT INTO collection_exclusions (id,user_id,thread_id,issue_id,created_at) "
            "VALUES (4,1,12,13,now())",
            "INSERT INTO collection_exclusions (id,user_id,provider,created_at) "
            "VALUES (4,1,'comicvine',now())",
            "INSERT INTO collection_exclusions (id,user_id,thread_id,created_at) "
            "VALUES (4,1,987654,now())",
            "INSERT INTO collection_exclusions (id,user_id,provider,external_volume_id,created_at) "
            "VALUES (4,1,'comicvine','4050-10',now())",
        ):
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(text(statement))
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert conn.execute(
            text("SELECT to_regclass('pg_temp.collection_exclusions')")
        ).scalar_one() is None

    connection = await async_db.connection()
    await connection.run_sync(verify)
