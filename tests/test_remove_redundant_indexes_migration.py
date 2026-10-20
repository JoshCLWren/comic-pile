"""Regression tests for the restartable downgrade of the redundant-index migration.

Revision ``c32320000001`` removes three indexes that unique constraints already
cover. Its downgrade has to survive a retried Alembic run: an earlier attempt
can leave some indexes restored, some still missing, and some in the invalid
state that an interrupted ``CREATE INDEX CONCURRENTLY`` leaves behind. A retry
must skip the indexes that are already restored, rebuild the invalid ones, and
create the missing ones instead of failing with "relation already exists".

The migration cannot be exercised through ``alembic upgrade``/``downgrade``
against the shared test database, so the tests below drive the migration module
directly: first against a recording operations stub that pins the issued DDL,
then against a real PostgreSQL catalog in a dedicated schema. The same fixture
also records the index bytes and the index write maintenance that the upgrade
removes, as issue #3219 requires.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

MIGRATION_PATH = (
    Path(__file__).parents[1] / "alembic/versions/c32320000001_remove_redundant_indexes.py"
)

# The indexes the downgrade restores: name, owning table, and covered columns.
RESTORED_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_issue_thread_position", "issues", ("thread_id", "position")),
    ("ix_user_preferences_user_id", "user_preferences", ("user_id",)),
    ("ix_recommendation_contexts_event_id", "recommendation_contexts", ("event_id",)),
)

# Catalog states the migration has to tell apart.
INDEX_MISSING = "missing"
INDEX_INVALID = "invalid"
INDEX_VALID = "valid"

# Bounds for the concurrent-build cancellation used to leave an invalid index.
POLL_ATTEMPTS = 200
POLL_INTERVAL_SECONDS = 0.05
CANCEL_TIMEOUT_SECONDS = 30.0

# Rows written to the fixture before and after the upgrade, per table.
FIXTURE_WRITES: dict[str, int] = {
    "issues": 200,
    "user_preferences": 50,
    "recommendation_contexts": 50,
}


def _load_migration() -> ModuleType:
    """Load the migration module under test.

    Returns:
        The imported migration module.
    """
    spec = importlib.util.spec_from_file_location(
        "remove_redundant_indexes_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeCatalogResult:
    """Result stub for the migration's index catalog lookup."""

    def __init__(self, row: tuple[bool] | None) -> None:
        """Store the row the catalog lookup should return.

        Args:
            row: The ``indisvalid`` row, or ``None`` when the index is absent.
        """
        self._row = row

    def first(self) -> tuple[bool] | None:
        """Return the single catalog row, or ``None`` when the index is absent.

        Returns:
            The stored catalog row.
        """
        return self._row


class _FakeBind:
    """Bind stub that answers the migration's index catalog lookup."""

    def __init__(self, states: dict[str, str]) -> None:
        """Store the catalog state of every index.

        Args:
            states: Mapping of index name to catalog state.
        """
        self._states = states

    def execute(
        self, statement: object, parameters: dict[str, object] | None = None
    ) -> _FakeCatalogResult:
        """Return the catalog row for the inspected index.

        Args:
            statement: The catalog query the migration issues.
            parameters: The bound query parameters.

        Returns:
            A result carrying the index catalog row.
        """
        assert parameters is not None
        name = str(parameters["index_name"])
        state = self._states.get(name, INDEX_MISSING)
        if state == INDEX_VALID:
            return _FakeCatalogResult((True,))
        if state == INDEX_INVALID:
            return _FakeCatalogResult((False,))
        return _FakeCatalogResult(None)


class _FakeContext:
    """Migration context stub for an online (non-offline) migration run."""

    def __init__(self) -> None:
        """Mark the context as an online migration run."""
        self.as_sql = False

    def autocommit_block(self) -> AbstractContextManager[None]:
        """Return a stand-in for Alembic's autocommit block.

        Returns:
            A context manager that performs no work.
        """
        return nullcontext()


class _FakeOperations:
    """Operations stub that records the DDL the migration issues."""

    def __init__(self, states: dict[str, str]) -> None:
        """Create the recorder for the given index catalog states.

        Args:
            states: Mapping of index name to catalog state.
        """
        self.executed: list[str] = []
        self.dropped: list[str] = []
        self.created: list[tuple[str, str, tuple[str, ...]]] = []
        self.create_options: list[dict[str, object]] = []
        self._context = _FakeContext()
        self._bind = _FakeBind(states)

    def get_context(self) -> _FakeContext:
        """Return the migration context stub.

        Returns:
            The migration context stub.
        """
        return self._context

    def get_bind(self) -> _FakeBind:
        """Return the bind stub used for catalog lookups.

        Returns:
            The bind stub.
        """
        return self._bind

    def execute(self, statement: object) -> None:
        """Record a statement the migration executed.

        Args:
            statement: The executed statement.
        """
        self.executed.append(str(statement))

    def drop_index(self, index_name: str, **options: object) -> None:
        """Record an index drop.

        Args:
            index_name: Name of the dropped index.
            options: Remaining drop options.
        """
        self.dropped.append(index_name)

    def create_index(
        self, index_name: str, table_name: str, columns: list[str], **options: object
    ) -> None:
        """Record an index creation.

        Args:
            index_name: Name of the created index.
            table_name: Table that owns the index.
            columns: Columns covered by the index.
            options: Remaining create options.
        """
        self.created.append((index_name, table_name, tuple(columns)))
        self.create_options.append(options)


def _run_downgrade(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, states: dict[str, str]
) -> _FakeOperations:
    """Run the migration downgrade against a recording operations stub.

    Args:
        monkeypatch: Fixture used to swap the migration's Alembic operations.
        module: The migration module under test.
        states: Mapping of index name to catalog state.

    Returns:
        The recorder holding the DDL the downgrade issued.
    """
    recorder = _FakeOperations(states)
    monkeypatch.setattr(module, "op", recorder)
    module.downgrade()
    return recorder


def test_migration_restores_the_documented_indexes() -> None:
    """The migration must keep restoring the three documented redundant indexes."""
    module = _load_migration()
    assert module.RESTORED_INDEXES == RESTORED_INDEXES


def test_downgrade_skips_indexes_an_earlier_attempt_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry must not rebuild indexes an earlier attempt already restored."""
    module = _load_migration()
    recorder = _run_downgrade(
        monkeypatch,
        module,
        {name: INDEX_VALID for name, _table, _columns in RESTORED_INDEXES},
    )

    assert recorder.dropped == []
    assert recorder.created == []


def test_downgrade_creates_indexes_a_previous_attempt_never_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry must create every index the earlier attempt never restored."""
    module = _load_migration()
    recorder = _run_downgrade(
        monkeypatch,
        module,
        {name: INDEX_MISSING for name, _table, _columns in RESTORED_INDEXES},
    )

    assert recorder.dropped == []
    assert recorder.created == list(RESTORED_INDEXES)


def test_downgrade_drops_and_rebuilds_indexes_left_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An index left invalid by a failed build must be dropped and rebuilt."""
    module = _load_migration()
    recorder = _run_downgrade(
        monkeypatch,
        module,
        {
            "ix_issue_thread_position": INDEX_INVALID,
            "ix_user_preferences_user_id": INDEX_VALID,
            "ix_recommendation_contexts_event_id": INDEX_MISSING,
        },
    )

    assert recorder.dropped == ["ix_issue_thread_position"]
    assert recorder.created == [
        ("ix_issue_thread_position", "issues", ("thread_id", "position")),
        ("ix_recommendation_contexts_event_id", "recommendation_contexts", ("event_id",)),
    ]


def test_downgrade_retry_repairs_every_index_after_a_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry must skip restored, rebuild invalid, and create missing indexes."""
    module = _load_migration()
    recorder = _run_downgrade(
        monkeypatch,
        module,
        {
            "ix_issue_thread_position": INDEX_INVALID,
            "ix_user_preferences_user_id": INDEX_VALID,
            "ix_recommendation_contexts_event_id": INDEX_MISSING,
        },
    )

    assert recorder.dropped == ["ix_issue_thread_position"]
    assert recorder.created == [
        ("ix_issue_thread_position", "issues", ("thread_id", "position")),
        ("ix_recommendation_contexts_event_id", "recommendation_contexts", ("event_id",)),
    ]
    # The rebuild must stay online and idempotent so a retried downgrade never
    # fails with "relation already exists".
    for options in recorder.create_options:
        assert options["postgresql_concurrently"] is True
        assert options["if_not_exists"] is True
        assert options["unique"] is False
    # The online DDL must run under explicit timeouts and restore them afterwards.
    assert "SET lock_timeout = '5s'" in recorder.executed
    assert "SET statement_timeout = '120s'" in recorder.executed
    assert "RESET lock_timeout" in recorder.executed
    assert "RESET statement_timeout" in recorder.executed


def _fixture_schema() -> str:
    """Return a unique schema name for the migration fixture.

    Returns:
        A schema name that no other test run can collide with.
    """
    return f"test_redundant_indexes_{os.getpid()}_{uuid.uuid4().hex[:8]}"


async def _create_fixture_tables(connection: AsyncConnection, schema: str) -> None:
    """Create the migration's tables, with their unique constraints, in a schema.

    Args:
        connection: Connection used to create the fixture.
        schema: Schema that holds the fixture.
    """
    await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await connection.execute(
        text(
            f'CREATE TABLE "{schema}".issues '
            "(id int GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, "
            "thread_id int, position int, status text)"
        )
    )
    await connection.execute(
        text(
            f'ALTER TABLE "{schema}".issues '
            "ADD CONSTRAINT uq_issue_thread_position UNIQUE (thread_id, position)"
        )
    )
    await connection.execute(
        text(
            f'CREATE TABLE "{schema}".user_preferences '
            "(id int GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, user_id int)"
        )
    )
    await connection.execute(
        text(
            f'ALTER TABLE "{schema}".user_preferences '
            "ADD CONSTRAINT uq_user_preferences_user_id UNIQUE (user_id)"
        )
    )
    await connection.execute(
        text(
            f'CREATE TABLE "{schema}".recommendation_contexts '
            "(id int GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, event_id int)"
        )
    )
    await connection.execute(
        text(
            f'ALTER TABLE "{schema}".recommendation_contexts '
            "ADD CONSTRAINT uq_recommendation_contexts_event_id UNIQUE (event_id)"
        )
    )
    await connection.commit()


async def _drop_fixture_schema(connection: AsyncConnection, schema: str) -> None:
    """Drop the fixture schema.

    Args:
        connection: Connection used to drop the fixture.
        schema: Schema that holds the fixture.
    """
    await connection.rollback()
    await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await connection.commit()


async def _create_redundant_indexes(builder: AsyncConnection, schema: str) -> None:
    """Create the redundant indexes the migration removes.

    Args:
        builder: Autocommit connection used for the concurrent builds.
        schema: Schema that holds the fixture.
    """
    await builder.execute(text(f'SET search_path TO "{schema}"'))
    await builder.execute(
        text(
            "CREATE INDEX CONCURRENTLY ix_issue_thread_position "
            "ON issues (thread_id, position)"
        )
    )
    await builder.execute(
        text("CREATE INDEX CONCURRENTLY ix_user_preferences_user_id ON user_preferences (user_id)")
    )
    await builder.execute(
        text(
            "CREATE INDEX CONCURRENTLY ix_recommendation_contexts_event_id "
            "ON recommendation_contexts (event_id)"
        )
    )


async def _write_fixture_rows(connection: AsyncConnection, schema: str) -> int:
    """Write a fixed number of rows to every fixture table.

    Args:
        connection: Connection used to write the rows.
        schema: Schema that holds the fixture.

    Returns:
        The number of rows written.
    """
    written = 0
    for table_name, rows in FIXTURE_WRITES.items():
        if table_name == "issues":
            await connection.execute(
                text(
                    f'INSERT INTO "{schema}".issues (thread_id, position, status) '
                    "SELECT g, g, 'unread' FROM generate_series(1, :rows) g"
                ),
                {"rows": rows},
            )
        else:
            key = "user_id" if table_name == "user_preferences" else "event_id"
            await connection.execute(
                text(
                    f'INSERT INTO "{schema}".{table_name} ({key}) '
                    "SELECT g FROM generate_series(1, :rows) g"
                ),
                {"rows": rows},
            )
        written += rows
    await connection.commit()
    return written


async def _measure_indexes(
    connection: AsyncConnection, schema: str, table_name: str
) -> tuple[int, int, int]:
    """Measure the index footprint of a fixture table.

    Args:
        connection: Connection used for the measurement.
        schema: Schema that holds the fixture.
        table_name: Table to measure.

    Returns:
        The number of indexes, their total size in bytes, and the number of
        index entries they maintain.
    """
    await connection.execute(text(f'ANALYZE "{schema}"."{table_name}"'))
    row = (
        await connection.execute(
            text(
                "SELECT count(*)::bigint, "
                "COALESCE(SUM(pg_relation_size(c.oid)), 0)::bigint, "
                "COALESCE(SUM(c.reltuples), 0)::bigint "
                "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                "WHERE i.indrelid = to_regclass(:qualified)"
            ),
            {"qualified": f'"{schema}"."{table_name}"'},
        )
    ).first()
    assert row is not None
    return int(row[0]), int(row[1]), int(row[2])


async def _index_row(
    connection: AsyncConnection, schema: str, index_name: str
) -> tuple[bool, int] | None:
    """Return the catalog row of an index.

    Args:
        connection: Connection used for the catalog lookup.
        schema: Schema that owns the index.
        index_name: Name of the inspected index.

    Returns:
        The ``(indisvalid, oid)`` row, or ``None`` when the index is absent.
    """
    row = (
        await connection.execute(
            text(
                "SELECT i.indisvalid, c.oid "
                "FROM pg_class c "
                "JOIN pg_index i ON i.indexrelid = c.oid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = :index_name AND n.nspname = :schema"
            ),
            {"index_name": index_name, "schema": schema},
        )
    ).first()
    return row


async def _leave_invalid_index(
    builder: AsyncConnection, worker: AsyncConnection, schema: str, index_name: str
) -> None:
    """Leave an invalid index behind by cancelling a concurrent build.

    Args:
        builder: Autocommit connection that runs the concurrent build.
        worker: Connection that holds the snapshot blocking the build.
        schema: Schema that owns the index.
        index_name: Name of the index to build.
    """
    await worker.execute(text("BEGIN"))
    # The open transaction keeps a snapshot alive, so the concurrent build waits
    # for it before it can mark the new index valid.
    await worker.execute(text(f'INSERT INTO "{schema}".issues VALUES (1, 1, 1, \'unread\')'))
    backend_pid = (await builder.execute(text("SELECT pg_backend_pid()"))).scalar_one()
    build = asyncio.create_task(
        builder.execute(
            text(
                f'CREATE INDEX CONCURRENTLY "{index_name}" '
                f'ON "{schema}".issues (thread_id, position)'
            )
        )
    )
    try:
        for _ in range(POLL_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            if build.done():
                # The build failed before it could leave an index behind.
                await build
                raise AssertionError("the concurrent index build finished unexpectedly")
            if await _index_row(worker, schema, index_name) is not None:
                break
        else:
            raise AssertionError("the concurrent index build never created an index")
        await worker.execute(text("SELECT pg_cancel_backend(:pid)"), {"pid": backend_pid})
        with pytest.raises(DBAPIError):
            await asyncio.wait_for(build, timeout=CANCEL_TIMEOUT_SECONDS)
    finally:
        if not build.done():
            build.cancel()
        await worker.execute(text("ROLLBACK"))


def _run_migration(module: ModuleType, schema: str, operation: str):
    """Build the callable that runs a migration operation against a schema.

    Args:
        module: The migration module under test.
        schema: Schema that holds the fixture.
        operation: Name of the migration operation to run.

    Returns:
        A callable that takes a synchronous connection and runs the operation.
    """

    def run(sync_connection) -> None:
        """Run the migration operation against the fixture schema."""
        sync_connection.execute(text(f'SET search_path TO "{schema}"'))
        sync_connection.commit()
        with Operations.context(MigrationContext.configure(sync_connection)):
            getattr(module, operation)()

    return run


@pytest.mark.asyncio
async def test_downgrade_restores_indexes_after_a_partial_attempt(db_engine: AsyncEngine) -> None:
    """The downgrade must repair a half-applied restore in a real PostgreSQL catalog."""
    module = _load_migration()
    schema = _fixture_schema()
    builder = await db_engine.connect()
    builder = await builder.execution_options(isolation_level="AUTOCOMMIT")
    worker = await db_engine.connect()
    try:
        await _create_fixture_tables(worker, schema)

        # An index an earlier downgrade attempt already restored.
        await builder.execute(
            text(
                f'CREATE INDEX CONCURRENTLY "ix_user_preferences_user_id" '
                f'ON "{schema}".user_preferences (user_id)'
            )
        )
        restored_row = await _index_row(worker, schema, "ix_user_preferences_user_id")
        assert restored_row is not None
        assert restored_row[0] is True

        # An index a failed concurrent build left invalid.
        await _leave_invalid_index(builder, worker, schema, "ix_issue_thread_position")
        invalid_row = await _index_row(worker, schema, "ix_issue_thread_position")
        assert invalid_row is not None
        assert invalid_row[0] is False

        # The third index stays missing because the earlier attempt never got to it.
        assert await _index_row(worker, schema, "ix_recommendation_contexts_event_id") is None

        await worker.run_sync(_run_migration(module, schema, "downgrade"))

        for index_name, _table, _columns in RESTORED_INDEXES:
            row = await _index_row(worker, schema, index_name)
            assert row is not None, f"{index_name} was not restored"
            assert row[0] is True, f"{index_name} was left in an unusable state"

        # The already restored index must be skipped, not dropped and rebuilt.
        final_row = await _index_row(worker, schema, "ix_user_preferences_user_id")
        assert final_row is not None
        assert final_row[1] == restored_row[1]
    finally:
        await _drop_fixture_schema(worker, schema)
        await worker.close()
        await builder.close()


@pytest.mark.asyncio
async def test_upgrade_records_index_bytes_and_index_writes_on_the_same_fixture(
    db_engine: AsyncEngine,
) -> None:
    """The upgrade must cut index bytes and index write maintenance on one fixture."""
    module = _load_migration()
    schema = _fixture_schema()
    builder = await db_engine.connect()
    builder = await builder.execution_options(isolation_level="AUTOCOMMIT")
    worker = await db_engine.connect()
    try:
        await _create_fixture_tables(worker, schema)
        await _create_redundant_indexes(builder, schema)

        # The fixture receives one fixed write workload, and the upgrade is
        # measured on the very same rows so both numbers describe one fixture.
        write_count = await _write_fixture_rows(worker, schema)
        before = {
            table_name: await _measure_indexes(worker, schema, table_name)
            for table_name in FIXTURE_WRITES
        }
        await worker.run_sync(_run_migration(module, schema, "upgrade"))
        after = {
            table_name: await _measure_indexes(worker, schema, table_name)
            for table_name in FIXTURE_WRITES
        }

        for table_name, rows in FIXTURE_WRITES.items():
            index_count_before, bytes_before, entries_before = before[table_name]
            index_count_after, bytes_after, entries_after = after[table_name]
            # The redundant index is gone, the primary key and the unique
            # constraint index stay.
            assert index_count_after == index_count_before - 1
            assert bytes_after < bytes_before
            # Every write maintains one entry per index, so the removed index
            # takes one index write per row with it.
            assert entries_before == rows * index_count_before
            assert entries_after == rows * index_count_after
            assert entries_after == entries_before - rows
        assert write_count == sum(FIXTURE_WRITES.values())
        # Uniqueness is untouched: the unique constraint indexes still exist and
        # the redundant indexes are gone.
        for index_name, _table, _columns in RESTORED_INDEXES:
            assert await _index_row(worker, schema, index_name) is None
        for constraint in (
            "uq_issue_thread_position",
            "uq_user_preferences_user_id",
            "uq_recommendation_contexts_event_id",
        ):
            assert await _index_row(worker, schema, constraint) is not None
    finally:
        await _drop_fixture_schema(worker, schema)
        await worker.close()
        await builder.close()
