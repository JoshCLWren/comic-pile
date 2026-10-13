"""Performance tests for ComicVine search endpoint optimization."""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import Timeout

from comic_pile.comicvine_provider import ComicVineClient, ComicVineResponse


@pytest.mark.asyncio
async def test_comicvine_search_performance_optimization():
    """Test that the optimized ComicVine search meets performance budget."""
    # Mock a successful ComicVine response
    mock_response_data = {
        "status_code": 1,
        "results": [
            {
                "id": 12345,
                "name": "Test Series",
                "publisher": {"id": 1, "name": "Test Publisher"},
                "start_year": 2020,
                "count_of_issues": 12,
                "site_detail_url": "https://comicvine.gamespot.com/test-series/12345/",
                "image": {"super_url": "https://example.com/image.jpg"},
            }
        ],
        "number_of_total_results": 1,
    }
    
    # Create ComicVine client with temporary cache directory
    with tempfile.TemporaryDirectory() as temp_dir:
        client = ComicVineClient(
            api_key="test-key",
            cache_dir=temp_dir,
            timeout_seconds=5.0,  # Reduced timeout for performance
        )
        
        # Mock the httpx client response
        with patch.object(client._http_client, 'get') as mock_get:
            mock_response = AsyncMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            
            # Test multiple requests to measure performance
            times = []
            for i in range(5):
                start_time = time.monotonic()
                
                result = await client.request(
                    "search",
                    "search",
                    {
                        "query": "test",
                        "resources": "volume",
                        "limit": 10,
                        "page": 1,
                    },
                )
                
                end_time = time.monotonic()
                duration = end_time - start_time
                times.append(duration)
                
                # Verify the response structure
                assert isinstance(result, ComicVineResponse)
                assert not result.from_cache  # Should be from live request
                assert result.payload == mock_response_data
            
            # Calculate average performance
            avg_time = sum(times) / len(times)
            max_time = max(times)
            min_time = min(times)
            
            print(f"Performance results:")
            print(f"  Average time: {avg_time:.3f}s")
            print(f"  Min time: {min_time:.3f}s")
            print(f"  Max time: {max_time:.3f}s")
            
            # Assert that performance meets budget (under 1000ms)
            assert avg_time < 1.0, f"Average time {avg_time:.3f}s exceeds 1000ms budget"
            assert max_time < 2.0, f"Max time {max_time:.3f}s exceeds reasonable threshold"
            
            # Verify httpx client is configured for performance
            assert isinstance(client._http_client.timeout, Timeout)
            assert client._http_client.timeout.timeout == 5.0
            assert client._http_client.timeout.connect == 1.5  # 30% of timeout
            assert client._http_client.limits.max_keepalive_connections == 20
            assert client._http_client.limits.max_connections == 100
            
            # Cleanup
            await client.close()


@pytest.mark.asyncio
async def test_comicvine_search_with_cache_performance():
    """Test that cached requests are significantly faster."""
    mock_response_data = {
        "status_code": 1,
        "results": [
            {
                "id": 12345,
                "name": "Test Series",
                "publisher": {"id": 1, "name": "Test Publisher"},
                "start_year": 2020,
                "count_of_issues": 12,
                "site_detail_url": "https://comicvine.gamespot.com/test-series/12345/",
                "image": {"super_url": "https://example.com/image.jpg"},
            }
        ],
        "number_of_total_results": 1,
    }
    
    with tempfile.TemporaryDirectory() as temp_dir:
        client = ComicVineClient(
            api_key="test-key",
            cache_dir=temp_dir,
            timeout_seconds=5.0,
        )
        
        # First request (should be live, slower)
        with patch.object(client._http_client, 'get') as mock_get:
            mock_response = AsyncMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            
            start_time = time.monotonic()
            result1 = await client.request(
                "search",
                "search",
                {"query": "test", "resources": "volume", "limit": 10, "page": 1},
            )
            first_request_time = time.monotonic() - start_time
            
            # Second request (should be cached, much faster)
            start_time = time.monotonic()
            result2 = await client.request(
                "search",
                "search",
                {"query": "test", "resources": "volume", "limit": 10, "page": 1},
            )
            second_request_time = time.monotonic() - start_time
            
            # Verify caching behavior
            assert result1.from_cache is False
            assert result2.from_cache is True
            
            # Cached requests should be much faster
            assert second_request_time < first_request_time / 10, \
                f"Cached request ({second_request_time:.3f}s) should be much faster than live request ({first_request_time:.3f}s)"
            
            print(f"Cache performance: Live={first_request_time:.3f}s, Cached={second_request_time:.3f}s")
            
            await client.close()


@pytest.mark.asyncio
async def test_comicvine_timeout_reduction():
    """Test that timeout reduction improves performance without breaking functionality."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Test with very short timeout
        client = ComicVineClient(
            api_key="test-key",
            cache_dir=temp_dir,
            timeout_seconds=2.0,  # Very short timeout
        )
        
        # Verify timeout is set correctly
        assert client.timeout_seconds == 2.0
        assert client._http_client.timeout.timeout == 2.0
        assert client._http_client.timeout.connect == 0.6  # 30% of timeout
        
        await client.close()


import tempfile