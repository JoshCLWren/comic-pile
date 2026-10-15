"""Tests for parallel pagination in ComicVine provider."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from comic_pile.comicvine_provider import ComicVineError, ComicVineResponse
from app.services.comicvine_resolution import get_comicvine_series_issues


class TestComicVineParallelPagination:
    """Test parallel pagination functionality in ComicVine provider."""

    @pytest.mark.asyncio
    async def test_parallel_pagination_complete_results(self):
        """Test that parallel pagination returns all expected issues in correct order."""
        # Mock the ComicVine client
        mock_client = Mock()
        
        # Mock responses for 3 pages (total 250 issues)
        page1_response = ComicVineResponse(
            payload={
                "number_of_total_results": 250,
                "results": [
                    {"id": 1, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100}},
                    {"id": 2, "issue_number": "2", "name": "Issue 2", "volume": {"id": 100}},
                    # ... 98 more issues for page 1
                ] * 100,  # Simplified - actual test would have 100 unique issues
            },
            from_cache=False,
        )
        
        page2_response = ComicVineResponse(
            payload={
                "number_of_total_results": 250,
                "results": [
                    {"id": 101, "issue_number": "101", "name": "Issue 101", "volume": {"id": 100}},
                    {"id": 102, "issue_number": "102", "name": "Issue 102", "volume": {"id": 100}},
                    # ... 98 more issues for page 2
                ] * 100,  # Simplified - actual test would have 100 unique issues
            },
            from_cache=False,
        )
        
        page3_response = ComicVineResponse(
            payload={
                "number_of_total_results": 250,
                "results": [
                    {"id": 201, "issue_number": "201", "name": "Issue 201", "volume": {"id": 100}},
                    {"id": 202, "issue_number": "202", "name": "Issue 202", "volume": {"id": 100}},
                    # ... 48 more issues for page 3
                ] * 50,  # Simplified - actual test would have 50 unique issues
            },
            from_cache=False,
        )
        
        # Mock the internal methods
        mock_client._fetch_single_page_issues = AsyncMock(
            side_effect=[
                page1_response.payload["results"][:100],  # Page 1
                page1_response.payload["results"][100:200],  # Page 2  
                page1_response.payload["results"][200:250],  # Page 3
            ]
        )
        
        # Test the parallel pagination
        result = await mock_client._fetch_volume_issues_parallel(100)
        
        # Verify all results are returned
        assert len(result) == 250
        
        # Verify correct order (issues should be in ascending order by ID)
        issue_ids = [issue["id"] for issue in result]
        assert issue_ids == list(range(1, 251))
        
        # Verify all issues belong to the correct volume
        for issue in result:
            volume = issue.get("volume")
            assert isinstance(volume, dict)
            assert volume.get("id") == 100

    @pytest.mark.asyncio
    async def test_parallel_pagination_single_page(self):
        """Test that single page volumes use the optimized single page path."""
        mock_client = Mock()
        
        # Mock response for single page (50 issues)
        single_page_response = ComicVineResponse(
            payload={
                "number_of_total_results": 50,
                "results": [
                    {"id": i, "issue_number": str(i), "name": f"Issue {i}", "volume": {"id": 100}}
                    for i in range(1, 51)
                ],
            },
            from_cache=False,
        )
        
        mock_client._fetch_single_page_issues = AsyncMock(
            return_value=single_page_response.payload["results"]
        )
        
        # Test single page handling
        result = await mock_client._fetch_volume_issues_parallel(100)
        
        # Verify results
        assert len(result) == 50
        assert all(issue["volume"]["id"] == 100 for issue in result)

    @pytest.mark.asyncio
    async def test_parallel_pagination_error_handling(self):
        """Test error handling when some pages fail."""
        mock_client = Mock()
        
        # Mock first page success, second page failure
        mock_client._fetch_single_page_issues = AsyncMock(
            side_effect=[
                [{"id": 1, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100}}],  # Page 1 success
                ComicVineError("API request failed"),  # Page 2 failure
            ]
        )
        
        # Should raise error due to partial failure
        with pytest.raises(ComicVineError):
            await mock_client._fetch_volume_issues_parallel(100)

    @pytest.mark.asyncio
    async def test_parallel_pagination_count_validation(self):
        """Test validation of total count vs actual results."""
        mock_client = Mock()
        
        # Mock responses where actual count doesn't match total
        mock_client._fetch_single_page_issues = AsyncMock(
            return_value=[
                {"id": 1, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100}},
                {"id": 2, "issue_number": "2", "name": "Issue 2", "volume": {"id": 100}},
            ]
        )
        
        # Should raise error due to count mismatch
        with pytest.raises(ComicVineError) as exc_info:
            await mock_client._fetch_volume_issues_parallel(100)
        
        assert "Expected 250 issues but received 2" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_service_layer_parallel_optimization(self):
        """Test that service layer uses parallel requests when series_name is not provided."""
        mock_client = Mock()
        
        # Mock volume and issues responses
        volume_response = ComicVineResponse(
            payload={
                "results": {
                    "id": 100,
                    "name": "Test Series",
                }
            },
            from_cache=False,
        )
        
        issues_response = [
            {"id": 1, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100}},
            {"id": 2, "issue_number": "2", "name": "Issue 2", "volume": {"id": 100}},
        ]
        
        mock_client.fetch_volume = AsyncMock(return_value=volume_response)
        mock_client.fetch_volume_issues = AsyncMock(return_value=issues_response)
        
        # Test service layer with empty series_name (should trigger parallel fetch)
        result = await get_comicvine_series_issues(mock_client, 100, series_name="")
        
        # Verify both volume and issues were fetched
        mock_client.fetch_volume.assert_called_once_with(100)
        mock_client.fetch_volume_issues.assert_called_once_with(100)
        
        # Verify result contains series name from volume
        assert result.series_name == "Test Series"
        assert len(result.issues) == 2

    @pytest.mark.asyncio 
    async def test_service_layer_with_pre fetched_series_name(self):
        """Test that service layer uses single request when series_name is provided."""
        mock_client = Mock()
        
        issues_response = [
            {"id": 1, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100}},
            {"id": 2, "issue_number": "2", "name": "Issue 2", "volume": {"id": 100}},
        ]
        
        mock_client.fetch_volume_issues = AsyncMock(return_value=issues_response)
        
        # Test service layer with pre-fetched series_name (should skip volume fetch)
        result = await get_comicvine_series_issues(mock_client, 100, series_name="Pre-fetched Series")
        
        # Verify only issues were fetched, not volume
        mock_client.fetch_volume_issues.assert_called_once_with(100)
        mock_client.fetch_volume.assert_not_called()
        
        # Verify result uses provided series name
        assert result.series_name == "Pre-fetched Series"
        assert len(result.issues) == 2

    @pytest.mark.asyncio
    async def test_volume_filter_validation(self):
        """Test that volume filter validation works correctly."""
        mock_client = Mock()
        
        # Mock response with mixed volume data (should be rejected)
        mock_client._fetch_single_page_issues = AsyncMock(
            return_value=[
                {"id": 1, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100}},  # Correct volume
                {"id": 2, "issue_number": "2", "name": "Issue 2", "volume": {"id": 200}},  # Wrong volume
            ]
        )
        
        # Should raise error due to mixed volume data
        with pytest.raises(ComicVineError) as exc_info:
            await mock_client._fetch_volume_issues_parallel(100)
        
        assert "ignored the requested volume filter" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_results_handling(self):
        """Test handling of empty results."""
        mock_client = Mock()
        
        # Mock empty response
        mock_client._fetch_single_page_issues = AsyncMock(return_value=[])
        
        # Should return empty list without error
        result = await mock_client._fetch_volume_issues_parallel(100)
        assert result == []