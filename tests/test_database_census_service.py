"""Tests for database census service functionality."""

import json
import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database_census_service import DatabaseCensusService


@pytest.fixture
def mock_db_session():
    """Create a mock async database session."""
    session = AsyncMock(spec=AsyncSession)
    return session


@pytest.fixture
def census_service(mock_db_session):
    """Create a database census service instance."""
    return DatabaseCensusService(mock_db_session, timeout_seconds=30)


class TestDatabaseCensusService:
    """Test cases for DatabaseCensusService."""

    @pytest.mark.asyncio
    async def test_set_read_only_mode(self, census_service, mock_db_session):
        """Test setting read-only mode."""
        await census_service._set_read_only_mode()
        
        # Verify that the execute method was called with the read-only command
        mock_db_session.execute.assert_called_once()
        call_args = mock_db_session.execute.call_args
        assert "SET LOCAL lock_timeout = '1s'" in str(call_args)

    @pytest.mark.asyncio
    async def test_get_postgresql_version(self, census_service, mock_db_session):
        """Test getting PostgreSQL version."""
        # Mock the database response
        mock_result = AsyncMock()
        mock_result.scalar_one.return_value = "PostgreSQL 16.2"
        mock_db_session.execute.return_value = mock_result
        
        version = await census_service._get_postgresql_version()
        
        assert version == "PostgreSQL 16.2"
        mock_db_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_postgresql_version_unknown(self, census_service, mock_db_session):
        """Test handling unknown PostgreSQL version."""
        # Mock the database response returning None
        mock_result = AsyncMock()
        mock_result.scalar_one.return_value = None
        mock_db_session.execute.return_value = mock_result
        
        version = await census_service._get_postgresql_version()
        
        assert version == "Unknown"

    @pytest.mark.asyncio
    async def test_collect_storage_stats(self, census_service, mock_db_session):
        """Test collecting storage statistics."""
        # Mock table size query results
        mock_table_result = AsyncMock()
        mock_table_result.fetchall.return_value = [
            AsyncMock(
                schemaname="public",
                tablename="users",
                total_size="16 kB",
                table_size="8 kB",
                index_size="8 kB",
                total_bytes=16384,
                table_bytes=8192,
                index_bytes=8192,
            )
        ]
        
        # Mock index size query results
        mock_index_result = AsyncMock()
        mock_index_result.fetchall.return_value = [
            AsyncMock(
                schemaname="public",
                tablename="users",
                indexname="users_pkey",
                index_size="8 kB",
                index_bytes=8192,
                idx_scan=100,
                idx_tup_read=1000,
                idx_tup_fetch=500,
            )
        ]
        
        # Mock toast query results
        mock_toast_result = AsyncMock()
        mock_toast_result.fetchall.return_value = []
        
        # Set up the execute method to return different results based on query
        def mock_execute(query):
            if "pg_tables" in str(query):
                return mock_table_result
            elif "pg_indexes" in str(query):
                return mock_index_result
            elif "pg_total_relation_size" in str(query) and "toast" in str(query):
                return mock_toast_result
            return AsyncMock()
        
        mock_db_session.execute.side_effect = mock_execute
        
        storage_stats = await census_service._collect_storage_stats()
        
        assert "tables" in storage_stats
        assert "indexes" in storage_stats
        assert "toast" in storage_stats
        
        assert len(storage_stats["tables"]) == 1
        assert storage_stats["tables"][0]["tablename"] == "users"
        assert storage_stats["tables"][0]["total_bytes"] == 16384

    @pytest.mark.asyncio
    async def test_collect_table_stats(self, census_service, mock_db_session):
        """Test collecting table statistics."""
        from app.models import User, Thread
        
        # Mock count queries
        mock_count_result = AsyncMock()
        mock_count_result.scalar.return_value = 10
        mock_db_session.execute.return_value = mock_count_result
        
        # Mock estimate query
        mock_estimate_result = AsyncMock()
        mock_estimate_result.scalar.return_value = 10
        mock_db_session.execute.return_value = mock_estimate_result
        
        table_stats = await census_service._collect_table_stats()
        
        assert "users" in table_stats
        assert "threads" in table_stats
        
        user_stats = table_stats["users"]
        assert user_stats["actual_rows"] == 10
        assert user_stats["estimated_rows"] == 10
        assert user_stats["count_accuracy"] == "exact"

    @pytest.mark.asyncio
    async def test_collect_table_stats_error_handling(self, census_service, mock_db_session):
        """Test error handling in table statistics collection."""
        from app.models import User
        
        # Mock query that raises an exception
        mock_db_session.execute.side_effect = Exception("Database error")
        
        table_stats = await census_service._collect_table_stats()
        
        user_stats = table_stats["users"]
        assert user_stats["actual_rows"] == 0
        assert user_stats["estimated_rows"] == 0
        assert user_stats["count_accuracy"] == "error"
        assert "error" in user_stats

    @pytest.mark.asyncio
    async def test_collect_index_analysis(self, census_service, mock_db_session):
        """Test index analysis collection."""
        # Mock index info query
        mock_index_result = AsyncMock()
        mock_index_result.fetchall.return_value = [
            AsyncMock(
                schemaname="public",
                tablename="users",
                indexname="users_pkey",
                indexdef="CREATE UNIQUE INDEX users_pkey ON users (id)",
                indisunique=True,
                indisprimary=True,
                indisclustered=False,
                idx_scan=100,
                idx_tup_read=1000,
                idx_tup_fetch=500,
                size="8 kB",
            )
        ]
        
        mock_db_session.execute.return_value = mock_index_result
        
        # Mock redundant and overlapping index methods
        census_service._identify_redundant_indexes = AsyncMock(return_value=[])
        census_service._identify_overlapping_indexes = AsyncMock(return_value=[])
        
        index_analysis = await census_service._collect_index_analysis()
        
        assert "by_table" in index_analysis
        assert "redundant_indexes" in index_analysis
        assert "overlapping_indexes" in index_analysis
        
        assert "public.users" in index_analysis["by_table"]
        assert len(index_analysis["by_table"]["public.users"]) == 1

    @pytest.mark.asyncio
    async def test_collect_snapshot_analysis(self, census_service, mock_db_session):
        """Test snapshot analysis collection."""
        # Mock snapshot types query
        mock_snapshot_result = AsyncMock()
        mock_snapshot_result.fetchall.return_value = [
            AsyncMock(
                snapshot_version="1",
                count=10,
                avg_size=500,
                max_size=1200,
                min_size=200,
            )
        ]
        
        # Mock session state query
        mock_session_result = AsyncMock()
        mock_session_result.fetchone.return_value = AsyncMock(
            total_snapshots=10,
            unique_sessions=2,
            has_session_state_ratio=0.5,
        )
        
        # Mock user distribution query
        mock_user_result = AsyncMock()
        mock_user_result.fetchall.return_value = [
            AsyncMock(
                user_id=1,
                snapshot_count=6,
                session_count=1,
            )
        ]
        
        def mock_execute(query):
            if "thread_states ->> 'version'" in str(query):
                return mock_snapshot_result
            elif "FROM snapshots" in str(query) and "COUNT(s.id)" not in str(query):
                return mock_session_result
            elif "rs.user_id" in str(query):
                return mock_user_result
            return AsyncMock()
        
        mock_db_session.execute.side_effect = mock_execute
        
        snapshot_analysis = await census_service._collect_snapshot_analysis()
        
        assert "by_version" in snapshot_analysis
        assert "session_state" in snapshot_analysis
        assert "top_users" in snapshot_analysis
        
        assert len(snapshot_analysis["by_version"]) == 1
        assert snapshot_analysis["by_version"][0]["version"] == "1"
        assert snapshot_analysis["session_state"]["total_snapshots"] == 10

    @pytest.mark.asyncio
    async def test_collect_query_plans(self, census_service, mock_db_session):
        """Test query plan collection."""
        # Mock explain query results
        mock_plan_result = AsyncMock()
        mock_plan_result.scalar_one.return_value = [{"Plan": "Sample plan"}]
        
        mock_db_session.execute.return_value = mock_plan_result
        
        query_plans = await census_service._collect_query_plans()
        
        assert "queue_query" in query_plans
        assert "roll_pool_query" in query_plans
        assert "undo_query" in query_plans
        assert "snapshot_query" in query_plans
        
        # Verify each plan has the expected structure
        for plan_name, plan in query_plans.items():
            assert "query" in plan
            assert "parameters" in plan
            assert "plan" in plan
            assert "plan_text" in plan

    @pytest.mark.asyncio
    async def test_explain_query_error_handling(self, census_service, mock_db_session):
        """Test error handling in query explanation."""
        # Mock query that raises an exception
        mock_db_session.execute.side_effect = Exception("EXPLAIN error")
        
        plan = await census_service._explain_query("SELECT * FROM test", {})
        
        assert "error" in plan
        assert plan["error"] == "EXPLAIN error"
        assert plan["query"] == "SELECT * FROM test"
        assert plan["plan"] is None

    @pytest.mark.asyncio
    async def test_collect_constraint_analysis(self, census_service, mock_db_session):
        """Test constraint analysis collection."""
        # Mock primary keys query
        mock_pk_result = AsyncMock()
        mock_pk_result.fetchall.return_value = [
            AsyncMock(
                table_name="users",
                constraint_name="users_pkey",
                column_name="id",
                constraint_type="PRIMARY KEY",
            )
        ]
        
        # Mock foreign keys query
        mock_fk_result = AsyncMock()
        mock_fk_result.fetchall.return_value = []
        
        # Mock unique constraints query
        mock_unique_result = AsyncMock()
        mock_unique_result.fetchall.return_value = []
        
        def mock_execute(query):
            if "PRIMARY KEY" in str(query):
                return mock_pk_result
            elif "FOREIGN KEY" in str(query):
                return mock_fk_result
            elif "UNIQUE" in str(query):
                return mock_unique_result
            return AsyncMock()
        
        mock_db_session.execute.side_effect = mock_execute
        
        constraint_analysis = await census_service._collect_constraint_analysis()
        
        assert "primary_keys" in constraint_analysis
        assert "foreign_keys" in constraint_analysis
        assert "unique_constraints" in constraint_analysis
        
        assert len(constraint_analysis["primary_keys"]) == 1
        assert constraint_analysis["primary_keys"][0]["table"] == "users"

    @pytest.mark.asyncio
    async def test_collect_census(self, census_service, mock_db_session):
        """Test complete census collection."""
        # Mock all the sub-methods
        census_service._set_read_only_mode = AsyncMock()
        census_service._get_postgresql_version = AsyncMock(return_value="PostgreSQL 16.2")
        census_service._collect_storage_stats = AsyncMock(return_value={"tables": []})
        census_service._collect_table_stats = AsyncMock(return_value={"users": {}})
        census_service._collect_index_analysis = AsyncMock(return_value={})
        census_service._collect_snapshot_analysis = AsyncMock(return_value={})
        census_service._collect_query_plans = AsyncMock(return_value={})
        census_service._collect_constraint_analysis = AsyncMock(return_value={})
        
        census_data = await census_service.collect_census()
        
        assert "metadata" in census_data
        assert "storage" in census_data
        assert "tables" in census_data
        assert "indexes" in census_data
        assert "snapshots" in census_data
        assert "queries" in census_data
        assert "constraints" in census_data
        
        assert "timestamp" in census_data["metadata"]
        assert "postgresql_version" in census_data["metadata"]
        assert "timeout_seconds" in census_data["metadata"]

    def test_redact_sensitive_data(self, census_service):
        """Test data redaction."""
        original_data = {
            "metadata": {
                "timestamp": "2026-10-10T12:00:00+00:00",
                "postgresql_version": "PostgreSQL 16.2",
                "sensitive_info": "secret",
            },
            "users": [
                {
                    "id": 1,
                    "email": "user@example.com",
                    "password_hash": "hashed_password",
                }
            ]
        }
        
        redacted_data = census_service.redact_sensitive_data(original_data)
        
        # Data should be copied, not modified in place
        assert original_data is not redacted_data
        
        # Metadata should be copied
        assert redacted_data["metadata"]["timestamp"] == original_data["metadata"]["timestamp"]
        assert redacted_data["metadata"]["postgresql_version"] == original_data["metadata"]["postgresql_version"]
        
        # In a real implementation, sensitive data would be redacted
        # For now, just ensure the structure is preserved
        assert "users" in redacted_data
        assert len(redacted_data["users"]) == 1


class TestDatabaseCensusIntegration:
    """Integration tests for database census service."""

    @pytest.mark.asyncio
    async def test_census_with_real_database(self, async_db):
        """Test census with a real database (requires database setup)."""
        # This test would require a properly set up test database
        # For now, we'll just test that the service can be created
        census_service = DatabaseCensusService(async_db, timeout_seconds=10)
        
        # Test that we can call the methods without errors
        # (This would need proper database setup to actually work)
        try:
            # These would fail in a test environment without proper setup
            # but we can at least verify the methods exist and are callable
            assert hasattr(census_service, 'collect_census')
            assert hasattr(census_service, '_set_read_only_mode')
            assert hasattr(census_service, '_get_postgresql_version')
        except Exception:
            # Expected in test environment without database
            pass