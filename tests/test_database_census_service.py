"""Tests for the read-only database census service (issue #3217)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Snapshot, Thread, User
from app.repositories.database_census_repository import DatabaseCensusRepository
from app.services.database_census_service import (
    CENSUS_QUERIES,
    CENSUS_REPORT_VERSION,
    DatabaseCensusService,
    contains_mutation,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

#: Recognisable values seeded by the fixture; none may appear in a report.
CENSUS_FIXTURE_USERNAME = "census-reader"
CENSUS_FIXTURE_EMAIL = "census-reader@example.invalid"
CENSUS_FIXTURE_PASSWORD = "census-password-hash-should-never-appear"
CENSUS_FIXTURE_TITLE = "Census Fixture Thread Title"

@pytest.fixture
def census_service() -> DatabaseCensusService:
    """Return a census service that never touches its session."""
    return DatabaseCensusService(AsyncSession(), timeout_seconds=30, sample_limit=10)

#: A structurally redundant narrow index and the wider index that covers it.
INDEX_CATALOG_ROWS: list[dict[str, object]] = [
    {
        "schema_name": "public",
        "table_name": "threads",
        "index_name": "threads_pkey",
        "is_unique": True,
        "is_primary": True,
        "is_partial": False,
        "predicate": None,
        "has_expressions": False,
        "access_method": "btree",
        "definition": "CREATE UNIQUE INDEX threads_pkey ON public.threads USING btree (id)",
        "size_bytes": 16384,
        "size_pretty": "16 kB",
        "scans": 12,
        "tuples_read": 120,
        "tuples_fetched": 60,
        "constraint_name": "threads_pkey",
        "constraint_type": "p",
        "constraint_deferrable": False,
        "constraint_deferred": False,
        "key_columns": ["id"],
    },
    {
        "schema_name": "public",
        "table_name": "threads",
        "index_name": "ix_threads_user_id",
        "is_unique": False,
        "is_primary": False,
        "is_partial": False,
        "predicate": None,
        "has_expressions": False,
        "access_method": "btree",
        "definition": "CREATE INDEX ix_threads_user_id ON public.threads USING btree (user_id)",
        "size_bytes": 8192,
        "size_pretty": "8192 bytes",
        "scans": 0,
        "tuples_read": 0,
        "tuples_fetched": 0,
        "constraint_name": None,
        "constraint_type": None,
        "constraint_deferrable": False,
        "constraint_deferred": False,
        "key_columns": ["user_id"],
    },
    {
        "schema_name": "public",
        "table_name": "threads",
        "index_name": "ix_threads_user_status_queue",
        "is_unique": False,
        "is_primary": False,
        "is_partial": False,
        "predicate": None,
        "has_expressions": False,
        "access_method": "btree",
        "definition": (
            "CREATE INDEX ix_threads_user_status_queue "
            "ON public.threads USING btree (user_id, status, queue_position)"
        ),
        "size_bytes": 16384,
        "size_pretty": "16 kB",
        "scans": 3,
        "tuples_read": 30,
        "tuples_fetched": 30,
        "constraint_name": None,
        "constraint_type": None,
        "constraint_deferrable": False,
        "constraint_deferred": False,
        "key_columns": ["user_id", "status", "queue_position"],
    },
    {
        "schema_name": "public",
        "table_name": "threads",
        "index_name": "ix_threads_status",
        "is_unique": False,
        "is_primary": False,
        "is_partial": False,
        "predicate": None,
        "has_expressions": False,
        "access_method": "btree",
        "definition": "CREATE INDEX ix_threads_status ON public.threads USING btree (status)",
        "size_bytes": 8192,
        "size_pretty": "8192 bytes",
        "scans": 0,
        "tuples_read": 0,
        "tuples_fetched": 0,
        "constraint_name": None,
        "constraint_type": None,
        "constraint_deferrable": False,
        "constraint_deferred": False,
        "key_columns": ["status"],
    },
    {
        "schema_name": "public",
        "table_name": "threads",
        "index_name": "ix_threads_open_partial",
        "is_unique": False,
        "is_primary": False,
        "is_partial": True,
        "predicate": "(status = 'active'::text)",
        "has_expressions": False,
        "access_method": "btree",
        "definition": (
            "CREATE INDEX ix_threads_open_partial ON public.threads "
            "USING btree (user_id) WHERE status = 'active'::text"
        ),
        "size_bytes": 4096,
        "size_pretty": "4096 bytes",
        "scans": 0,
        "tuples_read": 0,
        "tuples_fetched": 0,
        "constraint_name": None,
        "constraint_type": None,
        "constraint_deferrable": False,
        "constraint_deferred": False,
        "key_columns": ["user_id"],
    },
    {
        "schema_name": "public",
        "table_name": "threads",
        "index_name": "ix_threads_active_queue",
        "is_unique": False,
        "is_primary": False,
        "is_partial": False,
        "predicate": None,
        "has_expressions": False,
        "access_method": "btree",
        "definition": (
            "CREATE INDEX ix_threads_active_queue "
            "ON public.threads USING btree (status, queue_position)"
        ),
        "size_bytes": 8192,
        "size_pretty": "8192 bytes",
        "scans": 7,
        "tuples_read": 70,
        "tuples_fetched": 70,
        "constraint_name": None,
        "constraint_type": None,
        "constraint_deferrable": False,
        "constraint_deferred": False,
        "key_columns": ["status", "queue_position"],
    },
    {
        "schema_name": "public",
        "table_name": "threads",
        "index_name": "ix_threads_active_queue_created",
        "is_unique": False,
        "is_primary": False,
        "is_partial": False,
        "predicate": None,
        "has_expressions": False,
        "access_method": "btree",
        "definition": (
            "CREATE INDEX ix_threads_active_queue_created ON public.threads "
            "USING btree (status, queue_position, created_at)"
        ),
        "size_bytes": 16384,
        "size_pretty": "16 kB",
        "scans": 0,
        "tuples_read": 0,
        "tuples_fetched": 0,
        "constraint_name": None,
        "constraint_type": None,
        "constraint_deferrable": False,
        "constraint_deferred": False,
        "key_columns": ["status", "queue_position", "created_at"],
    },
    {
        "schema_name": "public",
        "table_name": "users",
        "index_name": "users_pkey",
        "is_unique": True,
        "is_primary": True,
        "is_partial": False,
        "predicate": None,
        "has_expressions": False,
        "access_method": "btree",
        "definition": "CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)",
        "size_bytes": 16384,
        "size_pretty": "16 kB",
        "scans": 5,
        "tuples_read": 50,
        "tuples_fetched": 50,
        "constraint_name": "users_pkey",
        "constraint_type": "p",
        "constraint_deferrable": False,
        "constraint_deferred": False,
        "key_columns": ["id"],
    },
]

class TestMutationGuard:
    """The census must never plan a statement that could write."""

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT id FROM threads",
            "WITH recent AS (SELECT id FROM events) SELECT * FROM recent",
            "SELECT t.id FROM threads t WHERE t.created_at > now()",
            "VALUES (1)",
        ],
    )
    def test_read_statements_are_accepted(self, sql: str) -> None:
        """Read statements are accepted."""
        assert contains_mutation(sql) is False

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO threads (title) VALUES ('x')",
            "UPDATE threads SET queue_position = 1",
            "DELETE FROM snapshots",
            "TRUNCATE TABLE users",
            "CREATE INDEX ix_new ON threads (id)",
            "DROP INDEX ix_threads_user_id",
            "ALTER TABLE threads ADD COLUMN x integer",
            "MERGE INTO threads USING events ON true",
            "WITH stale AS (DELETE FROM events RETURNING id) SELECT * FROM stale",
            "SELECT 1; VACUUM",
            "SET statement_timeout = 0",
            "-- harmless comment\n/* block */ UPDATE threads SET x = 1",
            "SELECT 'please delete this row' AS note",
        ],
    )
    def test_mutation_statements_are_rejected(self, sql: str) -> None:
        """Mutation statements are rejected."""
        assert contains_mutation(sql) is True

    def test_every_census_query_is_a_read(self) -> None:
        """Every census query is a read."""
        for name, (query, _parameters) in CENSUS_QUERIES.items():
            assert contains_mutation(query) is False, name

class TestServiceConstruction:
    """Bounded collection parameters are required, not optional."""

    @pytest.mark.parametrize("timeout", [0, -1])
    def test_rejects_non_positive_timeout(self, timeout: int) -> None:
        """Rejects non positive timeout."""
        with pytest.raises(ValueError, match="timeout_seconds"):
            DatabaseCensusService(None, timeout_seconds=timeout)  # type: ignore[arg-type]

    @pytest.mark.parametrize("sample_limit", [0, -5])
    def test_rejects_non_positive_sample_limit(self, sample_limit: int) -> None:
        """Rejects non positive sample limit."""
        with pytest.raises(ValueError, match="sample_limit"):
            DatabaseCensusService(None, sample_limit=sample_limit)  # type: ignore[arg-type]

    @pytest.mark.parametrize("timeout", [0, -3])
    async def test_repository_rejects_non_positive_timeout(self, timeout: int) -> None:
        """Repository rejects non positive timeout."""
        repository = DatabaseCensusRepository(AsyncSession())
        with pytest.raises(ValueError, match="positive integers"):
            await repository.begin_read_only_transaction(timeout)

class TestIndexRedundancyAnalysis:
    """Structural redundancy is a flag, never a removal verdict."""

    async def test_flags_narrow_index_covered_by_wider_index(
        self, census_service: DatabaseCensusService
    ) -> None:
        """Flags narrow index covered by wider index."""
        census_service.repository.index_catalog = _catalog_stub(INDEX_CATALOG_ROWS)  # type: ignore[method-assign]
        analysis = await census_service._collect_indexes()

        flagged = {
            (entry["index"], entry["covered_by"])
            for entry in analysis["potential_redundant_indexes"]
        }
        assert (
            "ix_threads_user_id",
            "ix_threads_user_status_queue",
        ) in flagged

    async def test_never_claims_confirmed_safe_removal(
        self, census_service: DatabaseCensusService
    ) -> None:
        """Never claims confirmed safe removal."""
        census_service.repository.index_catalog = _catalog_stub(INDEX_CATALOG_ROWS)  # type: ignore[method-assign]
        analysis = await census_service._collect_indexes()

        assert analysis["potential_redundant_indexes"]
        for entry in analysis["potential_redundant_indexes"]:
            assert entry["classification"] == "potential_redundant"
            assert entry["confirmed_safe_removal"] is False

    async def test_reports_constraint_backing_and_deferrability(
        self, census_service: DatabaseCensusService
    ) -> None:
        """Reports constraint backing and deferrability."""
        census_service.repository.index_catalog = _catalog_stub(INDEX_CATALOG_ROWS)  # type: ignore[method-assign]
        analysis = await census_service._collect_indexes()

        threads = {entry["name"]: entry for entry in analysis["by_table"]["threads"]}
        assert threads["threads_pkey"]["constraint_type"] == "p"
        assert threads["threads_pkey"]["constraint_deferrable"] is False
        assert threads["ix_threads_user_id"]["constraint_name"] is None
        assert threads["ix_threads_open_partial"]["predicate"] == "(status = 'active'::text)"
        assert threads["ix_threads_open_partial"]["is_partial"] is True

    async def test_does_not_flag_indexes_on_different_predicates(
        self, census_service: DatabaseCensusService
    ) -> None:
        """Does not flag indexes on different predicates."""
        census_service.repository.index_catalog = _catalog_stub(INDEX_CATALOG_ROWS)  # type: ignore[method-assign]
        analysis = await census_service._collect_indexes()

        flagged_names = {entry["index"] for entry in analysis["potential_redundant_indexes"]}
        assert "ix_threads_open_partial" not in flagged_names

    async def test_does_not_cross_tables(
        self, census_service: DatabaseCensusService
    ) -> None:
        """Does not cross tables."""
        census_service.repository.index_catalog = _catalog_stub(INDEX_CATALOG_ROWS)  # type: ignore[method-assign]
        analysis = await census_service._collect_indexes()

        for entry in analysis["potential_redundant_indexes"]:
            assert entry["table"] == "threads"

    async def test_reports_removal_blockers(
        self, census_service: DatabaseCensusService
    ) -> None:
        """Reports removal blockers."""
        census_service.repository.index_catalog = _catalog_stub(INDEX_CATALOG_ROWS)  # type: ignore[method-assign]
        analysis = await census_service._collect_indexes()

        entries = {
            entry["index"]: entry for entry in analysis["potential_redundant_indexes"]
        }
        assert "has_recorded_scans" not in entries["ix_threads_user_id"]["reasons"]
        assert "has_recorded_scans" in entries["ix_threads_active_queue"]["reasons"]

class TestRedaction:
    """No identifier-bearing value may survive redaction."""

    def test_replaces_bind_parameter_values(self, census_service: DatabaseCensusService) -> None:
        """Replaces bind parameter values."""
        report = {
            "queries": {
                "queue_listing": {
                    "query": "SELECT 1",
                    "parameters": {"user_id": 42, "page_size": 25},
                }
            }
        }
        redacted = census_service.redact(report)

        assert redacted["queries"]["queue_listing"]["parameters"] == {
            "user_id": "<sample-value>",
            "page_size": "<sample-value>",
        }
        assert report["queries"]["queue_listing"]["parameters"]["user_id"] == 42

    def test_drops_connection_metadata(self, census_service: DatabaseCensusService) -> None:
        """Drops connection metadata."""
        report = {
            "metadata": {
                "database_url": "postgresql+asyncpg://user:pw@host/db",
                "connection_string": "host=db",
                "credentials": {"password": "pw"},
                "postgresql_version": "PostgreSQL 16.2",
            }
        }
        redacted = census_service.redact(report)

        assert redacted["metadata"] == {"postgresql_version": "PostgreSQL 16.2"}

    def test_does_not_mutate_the_input_report(
        self, census_service: DatabaseCensusService
    ) -> None:
        """Does not mutate the input report."""
        report = {"queries": {"q": {"parameters": {"user_id": 7}}}}
        census_service.redact(report)

        assert report["queries"]["q"]["parameters"]["user_id"] == 7

class TestReadOnlyEnforcement:
    """The census transaction must reject writes at the database."""

    async def test_write_inside_census_transaction_is_rejected(
        self, async_db_committed: AsyncSession
    ) -> None:
        """Write inside census transaction is rejected."""
        repository = DatabaseCensusRepository(async_db_committed)
        await repository.begin_read_only_transaction(30)
        try:
            with pytest.raises(Exception) as excinfo:
                await async_db_committed.execute(
                    text("INSERT INTO users (username, password_hash) VALUES ('x', 'y')")
                )
            assert "read-only" in str(excinfo.value).lower()
        finally:
            await repository.rollback()

    async def test_statement_timeout_is_applied(
        self, async_db_committed: AsyncSession
    ) -> None:
        """Statement timeout is applied."""
        repository = DatabaseCensusRepository(async_db_committed)
        await repository.begin_read_only_transaction(30)
        try:
            result = await async_db_committed.execute(text("SHOW statement_timeout"))
            assert result.scalar() == "30s"
            read_only = await async_db_committed.execute(text("SHOW transaction_read_only"))
            assert read_only.scalar() == "on"
        finally:
            await repository.rollback()

class TestCensusAgainstPostgres:
    """End-to-end census against the PostgreSQL test database."""

    async def test_reports_separate_bytes_and_estimates(
        self, async_db_committed: AsyncSession
    ) -> None:
        """Reports separate bytes and estimates."""
        report = await DatabaseCensusService(async_db_committed, timeout_seconds=60).collect_census()

        assert report["report_version"] == CENSUS_REPORT_VERSION
        assert report["metadata"]["read_only_transaction"] is True
        assert report["metadata"]["postgresql_version"].startswith("PostgreSQL")
        assert report["metadata"]["collected_at"]

        assert report["storage"]["tables"]
        first = report["storage"]["tables"][0]
        assert first["total_bytes"] >= first["table_bytes"] >= 0
        assert first["table_bytes"] == first["total_bytes"] - first["index_bytes"]

        users = report["tables"]["users"]
        assert isinstance(users["measured_rows"], int)
        assert users["estimated_rows"] is None or isinstance(users["estimated_rows"], int)
        assert "estimate_available" in users

    async def test_indexes_and_constraints_are_inventoried(
        self, async_db_committed: AsyncSession
    ) -> None:
        """Indexes and constraints are inventoried."""
        report = await DatabaseCensusService(async_db_committed, timeout_seconds=60).collect_census()

        assert report["indexes"]["count"] > 0
        assert "threads" in report["indexes"]["by_table"]
        assert report["constraints"]["primary_keys"]
        assert report["constraints"]["foreign_keys"]
        assert all(
            "is_deferrable" in entry for entry in report["constraints"]["unique_constraints"]
        )

    async def test_query_plans_are_measured_and_parameters_redacted(
        self, async_db_committed: AsyncSession
    ) -> None:
        """Query plans are measured and parameters redacted."""
        report = await DatabaseCensusService(async_db_committed, timeout_seconds=60).collect_census()

        assert set(report["queries"]) == set(CENSUS_QUERIES)
        for name, plan in report["queries"].items():
            assert plan["plan"] is not None, name
            assert "error" not in plan, name
            assert set(plan["parameters"].values()) == {"<sample-value>"}, name

    async def test_report_never_contains_user_content(
        self, async_db_committed: AsyncSession
    ) -> None:
        """Report never contains user content."""
        await _seed_snapshot(async_db_committed)

        report = await DatabaseCensusService(async_db_committed, timeout_seconds=60).collect_census()

        rendered = repr(report)
        for secret in (
            CENSUS_FIXTURE_USERNAME,
            CENSUS_FIXTURE_EMAIL,
            CENSUS_FIXTURE_PASSWORD,
            CENSUS_FIXTURE_TITLE,
        ):
            assert secret not in rendered, secret

        def _keys(node: object) -> set[str]:
            if isinstance(node, dict):
                found = set(node)
                for value in node.values():
                    found |= _keys(value)
                return found
            if isinstance(node, list):
                found = set()
                for value in node:
                    found |= _keys(value)
                return found
            return set()

        # ``queries`` legitimately names columns in the plan text, so the
        # identifier check covers the measured sections only.
        measured = {key: value for key, value in report.items() if key != "queries"}
        assert "user_id" not in _keys(measured)
        assert "session_id" not in _keys(report["snapshots"])

    async def test_snapshot_growth_is_reported_for_seeded_readers(
        self, async_db_committed: AsyncSession
    ) -> None:
        """Snapshot growth is reported for seeded readers."""
        await _seed_snapshot(async_db_committed)

        report = await DatabaseCensusService(
            async_db_committed, timeout_seconds=60
        ).collect_census()

        growth = report["snapshots"]["workload_growth"]
        assert growth["sampled_readers"] >= 1
        # The seeded reader wrote two snapshots into one reading session, so at
        # least one bounded undo sample must report that session's full depth.
        depths = [sample["session_snapshot_rows"] for sample in growth["latest_undo"]]
        assert max(depths, default=0) >= 2
        assert any(
            sample["thread_state_bytes"] > 0 for sample in growth["latest_undo"]
        )

async def _seed_snapshot(session: AsyncSession) -> None:
    """Insert a minimal reader/thread/session/snapshot/event graph via the ORM."""
    user = User(
        username=CENSUS_FIXTURE_USERNAME,
        email=CENSUS_FIXTURE_EMAIL,
        password_hash=CENSUS_FIXTURE_PASSWORD,
    )
    session.add(user)
    await session.flush()

    thread = Thread(
        user_id=user.id,
        title=CENSUS_FIXTURE_TITLE,
        format="series",
        issues_remaining=3,
        total_issues=5,
        queue_position=1,
        status="active",
    )
    session.add(thread)
    await session.flush()

    reading_session = ReadingSession(user_id=user.id, start_die=6)
    session.add(reading_session)
    await session.flush()

    event = Event(type="roll", die=4, thread_id=thread.id, session_id=reading_session.id)
    session.add(event)
    await session.flush()

    session.add_all(
        [
            Snapshot(
                session_id=reading_session.id,
                event_id=event.id,
                thread_states={"version": "1", "threads": {}},
                session_state={"die": 4},
            ),
            Snapshot(
                session_id=reading_session.id,
                event_id=event.id,
                thread_states={"version": "1", "threads": {"1": {}}},
                session_state=None,
            ),
        ]
    )
    await session.commit()

def _catalog_stub(rows: list[dict[str, object]]):
    """Build an async stub returning fixed index catalog rows."""

    async def _index_catalog() -> list[dict[str, object]]:
        return list(rows)

    return _index_catalog
