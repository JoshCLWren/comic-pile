"""Test for ComicVine confirmed mapping TypeError handling."""

from __future__ import annotations

import logging
import pytest
from unittest.mock import AsyncMock, patch

from app.services.comicvine_fallback import refresh_issue_metadata


@pytest.mark.asyncio
async def test_refresh_issue_metadata_improved_typeerror_logging(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that TypeError details are captured and logged with more detail."""
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    
    # Set up logging to capture WARNING level logs
    with caplog.at_level(logging.WARNING):
        # Mock the database to raise a TypeError with a specific message
        def mock_get_side_effect(*args, **kwargs):
            if args and args[0] is not None:  # ExternalIdentity class
                raise TypeError("Expected int, got str - invalid external_id format")
            return None
        
        mock_db = AsyncMock()
        mock_db.get.side_effect = mock_get_side_effect
        mock_db.execute.return_value.scalar.return_value = True
        
        with patch("app.services.comicvine_fallback.AsyncSessionLocal", return_value=mock_db):
            result = await refresh_issue_metadata(1)
            
            # Should return False due to the TypeError
            assert result is False
            
            # Check that the error was logged with detailed TypeError information
            # Using caplog to capture the log output
            assert len(caplog.records) > 0, "Expected log records to be captured"
            
            # Find the specific error log
            error_log_found = False
            for record in caplog.records:
                if "comicvine_fallback_inline_failed" in record.message and "identity_id=1" in record.message:
                    error_log_found = True
                    # The error should now include more than just "TypeError"
                    assert "TypeError:" in record.message
                    # It should include some of the specific error details
                    assert "Expected int, got str" in record.message or "invalid external_id format" in record.message
                    break
            
            assert error_log_found, "Expected to find the detailed TypeError log message"


@pytest.mark.asyncio
async def test_refresh_issue_metadata_distinguishes_mapping_from_hydration_status(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that committed mappings are preserved even when hydration fails."""
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    
    # Mock the database to return a valid identity
    mock_db = AsyncMock()
    mock_identity = AsyncMock()
    mock_identity.id = 1
    mock_identity.provider = "comicvine"
    mock_identity.entity_type = "issue"
    mock_identity.external_id = "123"
    mock_identity.metadata_json = {"issue_number": "1"}
    
    mock_db.get.return_value = mock_identity
    mock_db.execute.return_value.scalar.return_value = True
    
    # Mock the hydrate function to raise TypeError
    async def mock_hydrate(*args, **kwargs):
        raise TypeError("Simulated TypeError during hydration")
    
    with patch("app.services.comicvine_fallback.AsyncSessionLocal", return_value=mock_db), \
         patch("app.comicvine_hydration.hydrate_issue", mock_hydrate):
        result = await refresh_issue_metadata(1)
        
        # Should return False due to the TypeError, but the mapping should still exist
        assert result is False
        
        # The identity mapping should still be accessed even though hydration failed
        mock_db.get.assert_called_once()
        call_args = mock_db.get.call_args
        assert call_args[0][0] is not None  # ExternalIdentity class


@pytest.mark.asyncio
async def test_refresh_issue_metadata_keeps_provider_io_bounded(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that provider I/O is bounded and doesn't block reader views."""
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    
    # Mock the database to simulate a lock timeout (non-blocking failure)
    mock_db = AsyncMock()
    mock_db.execute.side_effect = TimeoutError("advisory lock timeout")
    
    with patch("app.services.comicvine_fallback.AsyncSessionLocal", return_value=mock_db):
        result = await refresh_issue_metadata(1)
        
        # Should return False due to timeout, but this shouldn't block the reader
        assert result is False
        
        # Check that the error was logged appropriately
        assert len(caplog.records) > 0, "Expected log records to be captured"
        
        # Find the timeout error log
        timeout_log_found = False
        for record in caplog.records:
            if "comicvine_fallback_inline_failed" in record.message and "identity_id=1" in record.message:
                timeout_log_found = True
                assert "TimeoutError" in record.message
                assert "advisory lock timeout" in record.message
                break
        
        assert timeout_log_found, "Expected to find the TimeoutError log message"


@pytest.mark.asyncio 
async def test_refresh_issue_metadata_various_error_types(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that different error types are handled appropriately."""
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    
    # Test 1: TypeError with detailed message
    mock_db1 = AsyncMock()
    mock_db1.get.side_effect = TypeError("Cannot access 'id' from None - person_credits should be a list")
    
    with patch("app.services.comicvine_fallback.AsyncSessionLocal", return_value=mock_db1):
        result = await refresh_issue_metadata(1)
        assert result is False
        
        # Check that TypeError details are preserved
        typeerror_found = False
        for record in caplog.records:
            if "comicvine_fallback_inline_failed" in record.message and "identity_id=1" in record.message:
                if "TypeError: Cannot access 'id' from None" in record.message:
                    typeerror_found = True
                    break
        assert typeerror_found, "Expected to find detailed TypeError message"
    
    # Clear caplog
    caplog.clear()
    
    # Test 2: Other exception types (should only show type name)
    mock_db2 = AsyncMock()
    mock_db2.get.side_effect = ValueError("Invalid value provided")
    
    with patch("app.services.comicvine_fallback.AsyncSessionLocal", return_value=mock_db2):
        result = await refresh_issue_metadata(2)
        assert result is False
        
        # Check that other exceptions only show type name
        valueerror_found = False
        for record in caplog.records:
            if "comicvine_fallback_inline_failed" in record.message and "identity_id=2" in record.message:
                if "ValueError" in record.message and "Invalid value provided" not in record.message:
                    valueerror_found = True
                    break
        assert valueerror_found, "Expected to find ValueError with only type name"