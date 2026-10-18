"""Regression coverage for the redundant constraint-backed index migration (#3219).

Issue #3219 removes three ordinary indexes whose keys are already covered by the
backing index of a uniqueness constraint. These tests pin that contract:

- ``upgrade()`` drops exactly those three indexes and nothing else, so every
  uniqueness constraint, the deferred ``uq_issue_thread_position`` check, all
  foreign keys, and every unrelated index survive untouched;
- ``downgrade()`` restores the exact prior definitions (same names, same column
  order, still non-unique), so a rollback cannot silently promote an ordinary
  index into a unique one;
- ORM metadata declares exactly the surviving index/constraint set, so a
  ``create_all`` schema and a migrated schema cannot drift apart;
- the duplicate indexes cost measurable bytes on one fixed fixture, and the
  surviving unique index still serves ``(thread_id, position)`` ordering.

The upgrade and downgrade tests run the real Alembic operations against the
real PostgreSQL fixture instead of a stub, so they fail closed on any DDL that
does not actually apply.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, Table, UniqueConstraint, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, RecommendationContext, Thread, User, UserPreferences

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "d321900000001_drop_redundant_constraint_backed_indexes.py"
)

# Independent expectation of what issue #3219 removes, keyed by index name.
DROPPED_INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "ix_issue_thread_position": ("issues", ("thread_id", "position")),
    "ix_user_preferences_user_id": ("user_preferences", ("user_id",)),
    "ix_recommendation_contexts_event_id": ("recommendation_contexts", ("event_id",)),
}

# Unrelated coverage that must survive the migration untouched.
PRESERVED_INDEXES: frozenset[str] = frozenset(
    {
        "ix_issue_thread_id",
        "ix_issue_thread_is_read",
        "ix_issue_catalog_issue",
        "uq_issue_thread_position",
        "uq_issues_thread_id_id",
        "ix_recommendation_contexts_created_at",
        "ix_recommendation_contexts_intent",
    }
)

# Deterministic fixture for the index-byte accounting: 4 threads, 50 issues each.
FIXTURE_THREADS = 4
FIXTURE_ISSUES_PER_THREAD = 50


def _load_migration() -> ModuleType:
    """Import the migration module the way Alembic would."""
    spec = importlib.util.spec_from_file_location(
        "drop_redundant_constraint_backed_indexes", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _index_names(conn: Connection, table_name: str | None = None) -> set[str]:
    """Index names in the live schema, optionally restricted to one table."""
    sql = "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
    params: dict[str, str] = {}
    if table_name is not None:
        sql += " AND tablename = :table_name"
        params["table_name"] = table_name
    return {str(row[0]) for row in conn.execute(text(sql), params)}


def _index_definitions(conn: Connection, names: set[str]) -> dict[str, str]:
    """Map each requested index name to its ``pg_indexes.indexdef`` text."""
    rows = conn.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema()")
    ).all()
    return {str(row[0]): str(row[1]) for row in rows if str(row[0]) in names}


def _index_columns(indexdef: str) -> list[str]:
    """Extract the ordered column list from a ``pg_indexes.indexdef`` string."""
    inner = indexdef[indexdef.index("(") + 1 : indexdef.rindex(")")]
    return [part.strip().strip('"') for part in inner.split(",")]


def _relation_size_bytes(conn: Connection, relation_name: str) -> int:
    """On-disk size of a relation, or ``0`` when it is absent."""
    value = conn.execute(
        text("""
            SELECT pg_relation_size(c.oid)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema() AND c.relname = :relation_name
        """),
        {"relation_name": relation_name},
    ).scalar()
    return 0 if value is None else int(value)


def _table_index_bytes(conn: Connection, table_name: str) -> int:
    """Total bytes held by every index on ``table_name``."""
    return sum(_relation_size_bytes(conn, name) for name in _index_names(conn, table_name))


def _db_unique_column_sets(conn: Connection, table_name: str) -> set[frozenset[str]]:
    """Column sets protected by a unique constraint on the live table."""
    rows = conn.execute(
        text("""
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE c.contype = 'u'
              AND n.nspname = current_schema()
              AND t.relname = :table_name
        """),
        {"table_name": table_name},
    ).all()
    return {_parenthesized_columns(str(row[0])) for row in rows}


def _normalized_definition(indexdef: str) -> str:
    """Canonical comparison form for an index definition.

    Identifier quoting is presentation, not semantics: PostgreSQL records
    ``position`` and ``"position"`` the way the creating statement wrote them,
    so comparisons ignore quoting and whitespace while still pinning the
    operator class, column order and uniqueness.
    """
    return " ".join(indexdef.replace('"', "").upper().split())


def _parenthesized_columns(definition: str) -> frozenset[str]:
    """Read the column names out of a ``UNIQUE (a, b)`` style definition."""
    inner = definition[definition.index("(") + 1 : definition.rindex(")")]
    return frozenset(part.strip().strip('"') for part in inner.split(","))


def _orm_unique_column_sets(table: Table) -> set[frozenset[str]]:
    """Column sets the ORM protects with a unique constraint or unique index."""
    covered: set[frozenset[str]] = {
        frozenset(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    covered.update(
        frozenset(column.name for column in index.columns)
        for index in table.indexes
        if index.unique
    )
    return covered


def _create_pre_migration_indexes(conn: Connection) -> None:
    """Recreate the pre-migration deployed state the test schema no longer has.

    ``Base.metadata.create_all`` builds the fixture database from current ORM
    metadata, so the three dropped indexes are already absent. Recreating them
    makes the fixture match the schema an unmigrated database actually has.
    """
    conn.execute(text("CREATE INDEX ix_issue_thread_position ON issues (thread_id, position)"))
    conn.execute(text("CREATE INDEX ix_user_preferences_user_id ON user_preferences (user_id)"))
    conn.execute(
        text(
            "CREATE INDEX ix_recommendation_contexts_event_id "
            "ON recommendation_contexts (event_id)"
        )
    )


async def _seed_fixture(db: AsyncSession) -> None:
    """Populate the fixed fixture every byte measurement is taken on."""
    user = User(username="index_migration_fixture", created_at=datetime.now(UTC))
    db.add(user)
    await db.flush()

    for thread_number in range(1, FIXTURE_THREADS + 1):
        thread = Thread(
            title=f"Index migration fixture {thread_number}",
            format="comic",
            issues_remaining=FIXTURE_ISSUES_PER_THREAD,
            queue_position=thread_number,
            status="active",
            user_id=user.id,
        )
        db.add(thread)
        await db.flush()
        for position in range(1, FIXTURE_ISSUES_PER_THREAD + 1):
            db.add(
                Issue(
                    thread_id=thread.id,
                    issue_number=str(position),
                    position=position,
                    status="unread",
                )
            )
    await db.flush()


class _IndexRecorder:
    """Records the index DDL a migration emits without needing a database."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, statement: object, *_args: object, **_kwargs: object) -> None:
        """Capture a raw statement, such as the lock-timeout setting."""
        self.calls.append(("execute", (str(statement),)))

    def drop_index(self, index_name: str, *, table_name: str) -> None:
        """Capture a dropped index with its table."""
        self.calls.append(("drop_index", (index_name, table_name)))

    def create_index(self, index_name: str, table_name: str, columns: list[str]) -> None:
        """Capture a created index with its table and columns."""
        self.calls.append(("create_index", (index_name, table_name, tuple(columns))))


def _recorder_for(monkeypatch: pytest.MonkeyPatch, migration: ModuleType) -> _IndexRecorder:
    """Swap the migration's Alembic proxy for a recorder."""
    recorder = _IndexRecorder()
    monkeypatch.setattr(migration, "op", recorder, raising=False)
    return recorder


def test_upgrade_and_downgrade_emit_the_expected_index_ddl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The migration drops and restores exactly the three proven-redundant indexes."""
    migration = _load_migration()

    upgrade_recorder = _recorder_for(monkeypatch, migration)
    migration.upgrade()

    assert upgrade_recorder.calls == [
        # SET LOCAL, not SET: a session-scoped lock timeout would otherwise be
        # inherited by every later revision sharing the Alembic connection.
        ("execute", ("SET LOCAL lock_timeout = '5s'",)),
        ("drop_index", ("ix_issue_thread_position", "issues")),
        ("drop_index", ("ix_user_preferences_user_id", "user_preferences")),
        ("drop_index", ("ix_recommendation_contexts_event_id", "recommendation_contexts")),
    ]

    downgrade_recorder = _recorder_for(monkeypatch, migration)
    migration.downgrade()

    assert downgrade_recorder.calls == [
        ("execute", ("SET LOCAL lock_timeout = '5s'",)),
        ("create_index", ("ix_issue_thread_position", "issues", ("thread_id", "position"))),
        ("create_index", ("ix_user_preferences_user_id", "user_preferences", ("user_id",))),
        (
            "create_index",
            (
                "ix_recommendation_contexts_event_id",
                "recommendation_contexts",
                ("event_id",),
            ),
        ),
    ]


@pytest.mark.asyncio
async def test_upgrade_removes_only_the_redundant_indexes(async_db: AsyncSession) -> None:
    """Upgrade drops the duplicates and preserves every constraint and index."""
    migration = _load_migration()
    await _seed_fixture(async_db)

    def verify(conn: Connection) -> None:
        _create_pre_migration_indexes(conn)

        before = _index_names(conn)
        assert set(DROPPED_INDEXES) <= before
        bytes_before = {
            table_name: _table_index_bytes(conn, table_name)
            for table_name in ("issues", "user_preferences", "recommendation_contexts")
        }

        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()

        after = _index_names(conn)
        assert not set(DROPPED_INDEXES) & after
        assert PRESERVED_INDEXES <= after
        assert before - after == set(DROPPED_INDEXES)

        # The dropped duplicates really did hold storage on this same fixture.
        for table_name, previous_bytes in bytes_before.items():
            assert previous_bytes > 0, f"{table_name} had no index bytes before upgrade"
            assert _table_index_bytes(conn, table_name) < previous_bytes

        # Uniqueness is untouched, including the deferred Issue.position check.
        assert frozenset({"thread_id", "position"}) in _db_unique_column_sets(conn, "issues")
        assert frozenset({"user_id"}) in _db_unique_column_sets(conn, "user_preferences")
        assert frozenset({"event_id"}) in _db_unique_column_sets(conn, "recommendation_contexts")

        deferrability = conn.execute(
            text("""
                SELECT c.condeferrable, c.condeferred
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE c.conname = 'uq_issue_thread_position'
                  AND n.nspname = current_schema()
            """)
        ).all()
        assert [tuple(row) for row in deferrability] == [(True, True)]

        # The surviving unique index still covers (thread_id, position) in order.
        definitions = _index_definitions(conn, {"uq_issue_thread_position"})
        assert _index_columns(definitions["uq_issue_thread_position"]) == [
            "thread_id",
            "position",
        ]

    connection = await async_db.connection()
    await connection.run_sync(verify)


@pytest.mark.asyncio
async def test_downgrade_restores_the_exact_prior_index_definitions(
    async_db: AsyncSession,
) -> None:
    """Downgrade restores the same names, column order, and non-unique semantics."""
    migration = _load_migration()
    await _seed_fixture(async_db)

    def verify(conn: Connection) -> None:
        _create_pre_migration_indexes(conn)
        original = _index_definitions(conn, set(DROPPED_INDEXES))

        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert not set(DROPPED_INDEXES) & _index_names(conn)

        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()

        restored = _index_definitions(conn, set(DROPPED_INDEXES))
        assert set(restored) == set(DROPPED_INDEXES)
        for index_name, (_table_name, columns) in DROPPED_INDEXES.items():
            assert _index_columns(restored[index_name]) == list(columns)
            assert " UNIQUE " not in f" {restored[index_name].upper()} "

        # The restored definitions are the pre-migration definitions.
        assert {name: _normalized_definition(defn) for name, defn in restored.items()} == {
            name: _normalized_definition(defn) for name, defn in original.items()
        }

    connection = await async_db.connection()
    await connection.run_sync(verify)


def test_orm_metadata_matches_the_post_migration_schema() -> None:
    """Model metadata must declare exactly what the migration leaves behind."""
    declared_indexes = {
        index.name
        for model in (Issue, UserPreferences, RecommendationContext)
        for index in model.__table__.indexes
        if index.name is not None
    }

    assert not declared_indexes & set(DROPPED_INDEXES)
    assert _orm_unique_column_sets(Issue.__table__) >= {
        frozenset({"thread_id", "position"}),
        frozenset({"thread_id", "issue_number"}),
        frozenset({"thread_id", "id"}),
    }
    assert _orm_unique_column_sets(UserPreferences.__table__) >= {frozenset({"user_id"})}
    assert _orm_unique_column_sets(RecommendationContext.__table__) >= {frozenset({"event_id"})}