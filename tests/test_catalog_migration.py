"""Populated upgrade/downgrade coverage for the #3220 catalog identity migration.

The migration is additive-only. These tests create a temporary PostgreSQL
schema that mirrors the pre-migration parent shape (users, threads, issues,
external_identities), populate personal reader rows, then apply the exact
``upgrade()``/``downgrade()`` functions from the migration module. They prove
that personal primary keys and reader-owned state survive both directions and
that the new columns are nullable with no backfill.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, inspect, text

from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.external_identity import ExternalIdentity
from app.models.issue import Issue
from app.models.thread import Thread

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    REPOSITORY_ROOT
    / "alembic"
    / "versions"
    / "m5d300000001_add_catalog_identity_tables.py"
)
TEMP_SCHEMA = "catalog_migration_test"

# Minimal parent-state DDL: the tables the migration reads or writes, without
# the two new catalog tables and without the two new nullable columns.
PARENT_DDL = """
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255),
    password_changed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE threads (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    format VARCHAR(50) NOT NULL,
    issues_remaining INTEGER NOT NULL DEFAULT 0,
    total_issues INTEGER,
    next_unread_issue_id INTEGER,
    reading_progress VARCHAR(20),
    queue_position INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    last_rating DOUBLE PRECISION,
    last_activity_at TIMESTAMPTZ,
    notes TEXT,
    manual_creator_credits JSON NOT NULL DEFAULT '[]'::json,
    is_test BOOLEAN NOT NULL DEFAULT FALSE,
    is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id)
);
CREATE TABLE issues (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    issue_number VARCHAR(50) NOT NULL,
    position INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'unread',
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE external_identities (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,
    entity_type VARCHAR(20) NOT NULL,
    external_id VARCHAR(100) NOT NULL,
    external_url VARCHAR(500),
    metadata_json JSON NOT NULL DEFAULT '{}'::json,
    provider_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_external_identity_provider_entity
        UNIQUE (provider, entity_type, external_id),
    CONSTRAINT ck_external_identity_entity_type
        CHECK (entity_type IN ('issue', 'series'))
);
"""


def _load_migration_module() -> Any:
    """Load the catalog migration module by path."""
    spec = importlib.util.spec_from_file_location(
        "m5d300000001_add_catalog_identity_tables", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migration_module() -> Any:
    """Provide the loaded catalog migration module."""
    return _load_migration_module()


@pytest.fixture
def parent_schema(db_engine: Any) -> Iterator[Connection]:
    """Create a temporary pre-migration schema with populated personal rows.

    Yields a sync connection bound to the temporary schema. The schema is
    dropped on teardown so the shared test database is left unchanged.
    """

    def _prepare(sync_conn: Connection) -> None:
        sync_conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{TEMP_SCHEMA}" CASCADE')
        sync_conn.exec_driver_sql(f'CREATE SCHEMA "{TEMP_SCHEMA}"')
        sync_conn.exec_driver_sql(f'SET search_path TO "{TEMP_SCHEMA}"')
        for statement in PARENT_DDL.split(";"):
            stripped = statement.strip()
            if stripped:
                sync_conn.exec_driver_sql(stripped)

        now = datetime.now(UTC)
        sync_conn.exec_driver_sql(
            "INSERT INTO users (id, username, password_hash, created_at) VALUES "
            f"(1, 'migration_user', 'hash', '{now.isoformat()}')"
        )
        sync_conn.exec_driver_sql(
            "INSERT INTO threads (id, title, format, issues_remaining, total_issues, "
            "queue_position, status, notes, manual_creator_credits, is_test, is_blocked, "
            "created_at, user_id) VALUES "
            "(10, 'Personal Thread', 'Comic', 2, 3, 1, 'active', "
            "'reader note', '[]'::json, FALSE, FALSE, "
            f"'{now.isoformat()}', 1)"
        )
        sync_conn.exec_driver_sql(
            "INSERT INTO issues (id, thread_id, issue_number, position, status, "
            "read_at, created_at) VALUES "
            "(100, 10, '1', 1, 'read', "
            f"'{now.isoformat()}', '{now.isoformat()}'), "
            "(101, 10, '2', 2, 'unread', NULL, '{now.isoformat()}')"
        )
        sync_conn.exec_driver_sql(
            "INSERT INTO external_identities (id, provider, entity_type, external_id, "
            "metadata_json, created_at, updated_at) VALUES "
            f"(1, 'comicvine', 'series', '4000-1', '{{\"name\": \"Series\"}}', "
            f"'{now.isoformat()}', '{now.isoformat()}'), "
            f"(2, 'comicvine', 'issue', '5000-1', '{{\"name\": \"Issue 1\"}}', "
            f"'{now.isoformat()}', '{now.isoformat()}')"
        )

    def _teardown(sync_conn: Connection) -> None:
        sync_conn.exec_driver_sql('DROP SCHEMA IF EXISTS "%s" CASCADE' % TEMP_SCHEMA)

    async with db_engine.connect() as connection:
        await connection.run_sync(_prepare)
        try:
            yield connection
        finally:
            await connection.run_sync(_teardown)


def _run_migration(connection: Connection, migration_module: Any, direction: str) -> None:
    """Run the migration module's upgrade or downgrade against a sync connection."""
    migration_context = MigrationContext.configure(
        connection,
        opts={"version_table": "alembic_version", "as_sql": False},
    )
    with Operations.context(migration_context):
        if direction == "upgrade":
            migration_module.upgrade()
        else:
            migration_module.downgrade()


async def _seed_catalog_rows_and_links(connection: Connection) -> None:
    """After upgrade, create catalog rows and reader links with personal state intact."""
    now = datetime.now(UTC).isoformat()

    def _seed(sync_conn: Connection) -> None:
        sync_conn.exec_driver_sql(
            "INSERT INTO catalog_series (id, canonical_external_identity_id, "
            "created_at, updated_at) VALUES "
            f"(50, 1, '{now}', '{now}')"
        )
        sync_conn.exec_driver_sql(
            "INSERT INTO catalog_issues (id, canonical_external_identity_id, "
            "catalog_series_id, created_at, updated_at) VALUES "
            f"(60, 2, 50, '{now}', '{now}')"
        )
        sync_conn.exec_driver_sql(
            "UPDATE threads SET catalog_series_id = 50 WHERE id = 10"
        )
        sync_conn.exec_driver_sql(
            "UPDATE issues SET catalog_issue_id = 60 WHERE id = 100"
        )

    await connection.run_sync(_seed)


async def _assert_parent_personal_rows(connection: Connection) -> None:
    """Assert personal rows and their primary keys survived the migration."""

    def _check(sync_conn: Connection) -> None:
        user_row = sync_conn.exec_driver_sql(
            "SELECT id, username FROM users WHERE id = 1"
        ).one()
        assert user_row[0] == 1
        assert user_row[1] == "migration_user"

        thread_row = sync_conn.exec_driver_sql(
            "SELECT id, title, format, issues_remaining, total_issues, notes, user_id "
            "FROM threads WHERE id = 10"
        ).one()
        assert thread_row[0] == 10
        assert thread_row[1] == "Personal Thread"
        assert thread_row[2] == "Comic"
        assert thread_row[3] == 2
        assert thread_row[4] == 3
        assert thread_row[5] == "reader note"
        assert thread_row[6] == 1

        issue_rows = sync_conn.exec_driver_sql(
            "SELECT id, thread_id, issue_number, position, status FROM issues "
            "WHERE thread_id = 10 ORDER BY position"
        ).fetchall()
        assert [row[0] for row in issue_rows] == [100, 101]
        assert issue_rows[0][2] == "1"
        assert issue_rows[0][3] == 1
        assert issue_rows[0][4] == "read"
        assert issue_rows[1][2] == "2"
        assert issue_rows[1][4] == "unread"

        identity_count = sync_conn.exec_driver_sql(
            "SELECT count(*) FROM external_identities"
        ).scalar()
        assert identity_count == 2

    await connection.run_sync(_check)


def _column_is_nullable(connection: Connection, table: str, column: str) -> bool:
    def _check(sync_conn: Connection) -> bool:
        columns = {
            col["name"]: col["nullable"]
            for col in inspect(sync_conn).get_columns(table)
        }
        return bool(columns.get(column))

    return connection.run_sync(_check)


def _table_exists(connection: Connection, table: str) -> bool:
    def _check(sync_conn: Connection) -> bool:
        return inspect(sync_conn).has_table(table)

    return connection.run_sync(_check)


def _index_names(connection: Connection, table: str) -> set[str]:
    def _check(sync_conn: Connection) -> set[str]:
        return {
            index["name"]
            for index in inspect(sync_conn).get_indexes(table)
        }

    return connection.run_sync(_check)


@pytest.mark.asyncio
async def test_upgrade_is_additive_and_preserves_personal_rows(
    parent_schema: Connection,
    migration_module: Any,
) -> None:
    """Upgrade creates catalog tables, nullable links, and keeps personal rows."""
    await _assert_personal_rows(parent_schema)

    await parent_schema.run_sync(
        lambda sync_conn: _run_migration(sync_conn, migration_module, "upgrade")
    )

    assert _table_exists(parent_schema, "catalog_series")
    assert _table_exists(parent_schema, "catalog_issues")
    assert _column_is_nullable(parent_schema, "threads", "catalog_series_id")
    assert _column_is_nullable(parent_schema, "issues", "catalog_issue_id")

    series_indexes = _index_names(parent_schema, "catalog_series")
    assert "ix_catalog_series_external_identity" in series_indexes

    issue_indexes = _index_names(parent_schema, "catalog_issues")
    assert "ix_catalog_issues_external_identity" in issue_indexes
    assert "ix_catalog_issues_catalog_series" in issue_indexes

    thread_indexes = _index_names(parent_schema, "threads")
    assert "ix_thread_catalog_series" in thread_indexes

    reader_issue_indexes = _index_names(parent_schema, "issues")
    assert "ix_issue_catalog_issue" in reader_issue_indexes

    # No backfill: catalog tables start empty and reader links stay NULL.
    def _empty_catalog(sync_conn: Connection) -> None:
        assert sync_conn.exec_driver_sql(
            "SELECT count(*) FROM catalog_series"
        ).scalar() == 0
        assert sync_conn.exec_driver_sql(
            "SELECT count(*) FROM catalog_issues"
        ).scalar() == 0
        assert sync_conn.exec_driver_sql(
            "SELECT count(*) FROM threads WHERE catalog_series_id IS NOT NULL"
        ).scalar() == 0
        assert sync_conn.exec_driver_sql(
            "SELECT count(*) FROM issues WHERE catalog_issue_id IS NOT NULL"
        ).scalar() == 0

    await parent_schema.run_sync(_empty_catalog)
    await _assert_personal_rows(parent_schema)


@pytest.mark.asyncio
async def test_upgrade_then_link_then_downgrade_restores_parent_shape(
    parent_schema: Connection,
    migration_module: Any,
) -> None:
    """Upgrade, optional series link, then downgrade keep personal rows intact."""
    await parent_schema.run_sync(
        lambda sync_conn: _run_migration(sync_conn, migration_module, "upgrade")
    )
    await _seed_catalog_rows_and_links(parent_schema)
    await _assert_personal_rows(parent_schema)

    def _assert_linked(sync_conn: Connection) -> None:
        linked_series = sync_conn.exec_driver_sql(
            "SELECT catalog_series_id FROM threads WHERE id = 10"
        ).scalar()
        assert linked_series == 50
        linked_issue = sync_conn.exec_driver_sql(
            "SELECT catalog_issue_id FROM issues WHERE id = 100"
        ).scalar()
        assert linked_issue == 60

    await parent_schema.run_sync(_assert_linked)

    await parent_schema.run_sync(
        lambda sync_conn: _run_migration(sync_conn, migration_module, "downgrade")
    )

    assert not _table_exists(parent_schema, "catalog_series")
    assert not _table_exists(parent_schema, "catalog_issues")

    def _columns_gone(sync_conn: Connection) -> None:
        thread_columns = {
            col["name"] for col in inspect(sync_conn).get_columns("threads")
        }
        issue_columns = {
            col["name"] for col in inspect(sync_conn).get_columns("issues")
        }
        assert "catalog_series_id" not in thread_columns
        assert "catalog_issue_id" not in issue_columns

    await parent_schema.run_sync(_columns_gone)
    await _assert_personal_rows(parent_schema)


@pytest.mark.asyncio
async def test_downgrade_is_idempotent_after_upgrade_without_links(
    parent_schema: Connection,
    migration_module: Any,
) -> None:
    """Downgrade with NULL links (no catalog rows) still restores parent shape."""
    await parent_schema.run_sync(
        lambda sync_conn: _run_migration(sync_conn, migration_module, "upgrade")
    )
    await parent_schema.run_sync(
        lambda sync_conn: _run_migration(sync_conn, migration_module, "downgrade")
    )

    assert not _table_exists(parent_schema, "catalog_series")
    assert not _table_exists(parent_schema, "catalog_issues")
    await _assert_personal_rows(parent_schema)


def test_migration_source_has_no_backfill_or_network_calls() -> None:
    """The migration must not backfill personal rows or call provider networks."""
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    forbidden = (
        "UPDATE threads SET",
        "UPDATE issues SET",
        "INSERT INTO threads",
        "INSERT INTO issues",
        "UPDATE external_identities",
        "ComicVine",
        "requests.",
        "httpx",
        "urllib",
        "fetch_volume",
        "api_key",
    )
    for token in forbidden:
        assert token not in source, f"migration source must not contain {token!r}"

    # No bulk personal-row iteration in upgrade.
    upgrade_start = source.index("def upgrade()")
    downgrade_start = source.index("def downgrade()")
    upgrade_body = source[upgrade_start:downgrade_start]
    assert "for " not in upgrade_body
    assert "execute(" not in upgrade_body or "op.execute(" not in upgrade_body
