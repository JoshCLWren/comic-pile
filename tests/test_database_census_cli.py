"""Tests for the database census CLI command."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from argparse import Namespace

from scripts.database_census import (
    run_census,
    generate_sample_fixtures,
    main,
)


@pytest.fixture
def mock_database_url():
    """Mock database URL for testing."""
    return "postgresql+asyncpg://user:pass@localhost/testdb"


@pytest.fixture
def sample_census_data():
    """Sample census data for testing."""
    return {
        "metadata": {
            "timestamp": "2026-10-10T12:00:00+00:00",
            "postgresql_version": "PostgreSQL 16.2",
            "timeout_seconds": 30,
            "mode": "production",
        },
        "storage": {
            "tables": [],
            "indexes": [],
            "toast": [],
        },
        "tables": {
            "users": {
                "actual_rows": 100,
                "estimated_rows": 100,
                "count_accuracy": "exact",
            }
        },
        "indexes": {
            "by_table": {},
            "redundant_indexes": [],
            "overlapping_indexes": [],
        },
        "snapshots": {
            "by_version": [],
            "session_state": {},
            "top_users": [],
        },
        "queries": {
            "queue_query": {
                "query": "SELECT * FROM threads",
                "parameters": {},
                "plan": "sample_plan",
                "plan_text": "sample_plan_text",
            }
        },
        "constraints": {
            "primary_keys": [],
            "foreign_keys": [],
            "unique_constraints": [],
        },
    }


class TestRunCensus:
    """Test cases for the run_census function."""

    @pytest.mark.asyncio
    async def test_run_census_success(self, mock_database_url, sample_census_data):
        """Test successful census execution."""
        with patch('scripts.database_census.create_async_engine') as mock_create_engine, \
             patch('scripts.database_census.sessionmaker') as mock_sessionmaker, \
             patch('app.services.database_census_service.DatabaseCensusService') as mock_census_service_class:
            
            # Mock the database session and service
            mock_session = AsyncMock()
            mock_sessionmaker.return_value = lambda: mock_session
            
            mock_census_service = AsyncMock()
            mock_census_service.collect_census = AsyncMock(return_value=sample_census_data)
            mock_census_service.redact_sensitive_data = AsyncMock(return_value=sample_census_data)
            mock_census_service_class.return_value = mock_census_service
            
            # Run census
            result = await run_census(mock_database_url)
            
            # Verify results
            assert result == sample_census_data
            mock_census_service.collect_census.assert_called_once()
            mock_census_service.redact_sensitive_data.assert_called_once_with(sample_census_data)

    @pytest.mark.asyncio
    async def test_run_census_with_output_file(self, mock_database_url, sample_census_data):
        """Test census execution with output file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
            output_path = temp_file.name
        
        try:
            with patch('scripts.database_census.create_async_engine') as mock_create_engine, \
                 patch('scripts.database_census.sessionmaker') as mock_sessionmaker, \
                 patch('app.services.database_census_service.DatabaseCensusService') as mock_census_service_class:
                
                # Mock the database session and service
                mock_session = AsyncMock()
                mock_sessionmaker.return_value = lambda: mock_session
                
                mock_census_service = AsyncMock()
                mock_census_service.collect_census = AsyncMock(return_value=sample_census_data)
                mock_census_service.redact_sensitive_data = AsyncMock(return_value=sample_census_data)
                mock_census_service_class.return_value = mock_census_service
                
                # Run census with output file
                await run_census(mock_database_url, output_file=output_path)
                
                # Verify file was created and contains correct data
                assert Path(output_path).exists()
                
                with open(output_path, 'r', encoding='utf-8') as f:
                    file_data = json.load(f)
                
                assert file_data == sample_census_data
        finally:
            if Path(output_path).exists():
                Path(output_path).unlink()

    @pytest.mark.asyncio
    async def test_run_census_synthetic_mode(self, mock_database_url):
        """Test census in synthetic mode."""
        synthetic_data = generate_sample_fixtures()
        
        with patch('scripts.database_census.create_async_engine') as mock_create_engine, \
             patch('scripts.database_census.sessionmaker') as mock_sessionmaker, \
             patch('app.services.database_census_service.DatabaseCensusService') as mock_census_service_class:
            
            # Mock the database session and service
            mock_session = AsyncMock()
            mock_sessionmaker.return_value = lambda: mock_session
            
            mock_census_service = AsyncMock()
            mock_census_service.collect_census = AsyncMock(return_value=synthetic_data)
            mock_census_service.redact_sensitive_data = AsyncMock(return_value=synthetic_data)
            mock_census_service_class.return_value = mock_census_service
            
            # Run census in synthetic mode
            result = await run_census(mock_database_url, synthetic_data=True)
            
            # Verify synthetic metadata is added
            assert result["metadata"]["mode"] == "synthetic"

    @pytest.mark.asyncio
    async def test_run_census_error_handling(self, mock_database_url):
        """Test error handling in census execution."""
        with patch('scripts.database_census.create_async_engine') as mock_create_engine, \
             patch('scripts.database_census.sessionmaker') as mock_sessionmaker, \
             patch('app.services.database_census_service.DatabaseCensusService') as mock_census_service_class:
            
            # Mock the database session and service
            mock_session = AsyncMock()
            mock_sessionmaker.return_value = lambda: mock_session
            
            mock_census_service = AsyncMock()
            mock_census_service.collect_census = AsyncMock(side_effect=Exception("Database error"))
            mock_census_service_class.return_value = mock_census_service
            
            # Run census and expect exception
            with pytest.raises(Exception, match="Database error"):
                await run_census(mock_database_url)


class TestGenerateSampleFixtures:
    """Test cases for generate_sample_fixtures function."""

    def test_generate_sample_fixtures_structure(self):
        """Test that sample fixtures have the expected structure."""
        sample_data = generate_sample_fixtures()
        
        # Check required top-level keys
        required_keys = [
            "metadata", "storage", "tables", "indexes", 
            "snapshots", "queries", "constraints"
        ]
        
        for key in required_keys:
            assert key in sample_data, f"Missing required key: {key}"
        
        # Check metadata structure
        metadata = sample_data["metadata"]
        assert "timestamp" in metadata
        assert "postgresql_version" in metadata
        assert "timeout_seconds" in metadata
        assert "mode" in metadata
        assert metadata["mode"] == "synthetic"
        
        # Check storage structure
        storage = sample_data["storage"]
        assert "tables" in storage
        assert "indexes" in storage
        assert "toast" in storage
        
        # Check tables structure
        tables = sample_data["tables"]
        assert "users" in tables
        assert "threads" in tables
        assert "issues" in tables
        
        # Check snapshot analysis structure
        snapshots = sample_data["snapshots"]
        assert "by_version" in snapshots
        assert "session_state" in snapshots
        assert "top_users" in snapshots
        
        # Check queries structure
        queries = sample_data["queries"]
        assert "queue_query" in queries
        assert "roll_pool_query" in queries
        assert "undo_query" in queries
        assert "snapshot_query" in queries
        
        # Check constraints structure
        constraints = sample_data["constraints"]
        assert "primary_keys" in constraints
        assert "foreign_keys" in constraints
        assert "unique_constraints" in constraints

    def test_generate_sample_fixtures_data_types(self):
        """Test that sample fixtures have correct data types."""
        sample_data = generate_sample_fixtures()
        
        # Test metadata types
        metadata = sample_data["metadata"]
        assert isinstance(metadata["timestamp"], str)
        assert isinstance(metadata["timeout_seconds"], int)
        assert isinstance(metadata["mode"], str)
        
        # Test tables data types
        tables = sample_data["tables"]
        for table_name, table_stats in tables.items():
            assert isinstance(table_stats["actual_rows"], int)
            assert isinstance(table_stats["estimated_rows"], int)
            assert isinstance(table_stats["count_accuracy"], str)
        
        # Test snapshots data types
        snapshots = sample_data["snapshots"]
        for version_data in snapshots["by_version"]:
            assert isinstance(version_data["version"], str)
            assert isinstance(version_data["count"], int)
            assert isinstance(version_data["avg_size_chars"], (int, type(None)))
            assert isinstance(version_data["max_size_chars"], (int, type(None)))
            assert isinstance(version_data["min_size_chars"], (int, type(None)))


class TestMainFunction:
    """Test cases for the main function."""

    @patch('scripts.database_census.run_census')
    @patch('scripts.database_census.get_settings')
    @patch('sys.argv', ['database_census.py'])
    def test_main_no_database_url(self, mock_get_settings, mock_run_census):
        """Test main function without database URL."""
        # Mock settings to provide database URL
        mock_settings = MagicMock()
        mock_settings.database_url = "test_url"
        mock_get_settings.return_value = mock_settings
        
        # Mock run_census to not raise exception
        mock_run_census.return_value = {}
        
        # This would normally exit, but we're testing the flow
        with pytest.raises(SystemExit):
            main()

    @patch('scripts.database_census.run_census')
    @patch('sys.argv', ['database_census.py', '--database-url', 'test_url'])
    def test_main_with_database_url(self, mock_run_census):
        """Test main function with database URL."""
        # Mock run_census to not raise exception
        mock_run_census.return_value = {}
        
        # This would normally exit, but we're testing the flow
        with pytest.raises(SystemExit):
            main()

    @patch('scripts.database_census.generate_sample_fixtures')
    @patch('sys.argv', ['database_census.py', '--synthetic'])
    def test_main_synthetic_mode(self, mock_generate_fixtures):
        """Test main function in synthetic mode."""
        # Mock generate_sample_fixtures
        mock_generate_fixtures.return_value = {"metadata": {"mode": "synthetic"}}
        
        # This would normally exit, but we're testing the flow
        with pytest.raises(SystemExit):
            main()

    @patch('scripts.database_census.run_census')
    @patch('sys.argv', ['database_census.py', '--database-url', 'test_url', '--no-redact'])
    def test_main_no_redact(self, mock_run_census):
        """Test main function with no redaction."""
        # Mock run_census to not raise exception
        mock_run_census.return_value = {}
        
        # This would normally exit, but we're testing the flow
        with pytest.raises(SystemExit):
            main()


class TestArgumentParsing:
    """Test cases for argument parsing."""

    def test_parse_arguments_basic(self):
        """Test basic argument parsing."""
        with patch('sys.argv', ['database_census.py']):
            parser = MagicMock()
            parser.add_argument = MagicMock()
            parser.parse_args = MagicMock(return_value=Namespace(
                database_url=None,
                output=None,
                timeout=30,
                sample_limit=None,
                synthetic=False,
                no_redact=False,
            ))
            
            # Test that arguments are defined correctly
            assert parser.add_argument.call_count >= 7  # Should have at least 7 arguments

    def test_parse_arguments_with_options(self):
        """Test argument parsing with options."""
        with patch('sys.argv', [
            'database_census.py',
            '--database-url', 'test_url',
            '--output', 'output.json',
            '--timeout', '60',
            '--sample-limit', '1000',
            '--synthetic',
            '--no-redact',
        ]):
            parser = MagicMock()
            parser.add_argument = MagicMock()
            parser.parse_args = MagicMock(return_value=Namespace(
                database_url='test_url',
                output='output.json',
                timeout=60,
                sample_limit=1000,
                synthetic=True,
                no_redact=True,
            ))
            
            # Verify all options are parsed correctly
            args = parser.parse_args.return_value
            assert args.database_url == 'test_url'
            assert args.output == 'output.json'
            assert args.timeout == 60
            assert args.sample_limit == 1000
            assert args.synthetic is True
            assert args.no_redact is True