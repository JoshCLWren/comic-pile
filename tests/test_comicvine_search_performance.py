"""Performance tests for ComicVine search endpoint optimization."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.comicvine_resolution import search_comicvine_series
from comic_pile.comicvine_provider import ComicVineResponse

EXPECTED_SEARCH_FIELD_LIST = (
    "id,name,publisher,start_year,count_of_issues,site_detail_url,image"
)


@pytest.mark.asyncio
async def test_search_series_performance_optimization() -> None:
    """Test that search performance is optimized for fast response times."""
    # Mock a fast ComicVine response
    mock_payload = {
        "results": [
            {
                "id": 471,
                "name": "Ultimate Spider-Man",
                "publisher": {"name": "Marvel"},
                "start_year": "2000",
                "count_of_issues": "160",
                "site_detail_url": "https://comicvine.gamespot.com/volume/4050-471/",
            }
        ],
        "number_of_total_results": 1,
    }

    # Create a mock client that simulates a fast response
    mock_client = MagicMock()
    mock_client.request = AsyncMock(
        return_value=ComicVineResponse(payload=mock_payload, from_cache=False, cache_key="test")
    )

    # Measure performance
    start_time = time.perf_counter()
    result = await search_comicvine_series(mock_client, "Ultimate Spider-Man")
    end_time = time.perf_counter()

    response_time = (end_time - start_time) * 1000  # Convert to ms

    # Verify the response is correct
    assert len(result.results) == 1
    assert result.results[0].name == "Ultimate Spider-Man"
    assert result.results[0].start_year == 2000
    assert result.results[0].issue_count == 160

    # Performance assertion: should complete in under 100ms (much faster than 1000ms budget)
    assert response_time < 100, f"Search took {response_time:.2f}ms, expected < 100ms"

    # Verify the client was called with optimized parameters
    mock_client.request.assert_called_once()
    call_args = mock_client.request.call_args
    assert call_args[0][2]["field_list"] == EXPECTED_SEARCH_FIELD_LIST


@pytest.mark.asyncio
async def test_search_series_caching_performance() -> None:
    """Test that cached responses are very fast."""
    mock_payload = {
        "results": [
            {
                "id": 114402,
                "name": "Ultimate Spider-Man 2024",
                "publisher": {"name": "Marvel"},
                "start_year": "2024",
                "count_of_issues": "18",
                "site_detail_url": "https://comicvine.gamespot.com/volume/4050-114402/",
            }
        ],
        "number_of_total_results": 1,
    }

    # Create a mock client that simulates a cached response
    mock_client = MagicMock()
    mock_client.request = AsyncMock(
        return_value=ComicVineResponse(payload=mock_payload, from_cache=True, cache_key="cached")
    )

    # Measure cached response performance
    start_time = time.perf_counter()
    result = await search_comicvine_series(mock_client, "Ultimate Spider-Man 2024")
    end_time = time.perf_counter()

    response_time = (end_time - start_time) * 1000  # Convert to ms

    # Verify the response is correct
    assert len(result.results) == 1
    assert result.results[0].name == "Ultimate Spider-Man 2024"

    # Cached responses should be extremely fast
    assert response_time < 10, f"Cached search took {response_time:.2f}ms, expected < 10ms"


@pytest.mark.asyncio
async def test_search_series_field_optimization() -> None:
    """Test that the search requests every field the UI renders, including covers."""
    mock_payload = {
        "results": [
            {
                "id": 100,
                "name": "Batman",
                "publisher": {"name": "DC Comics"},
                "start_year": "1939",
                "count_of_issues": "1000",
                "site_detail_url": "https://comicvine.gamespot.com/volume/4050-100/",
            }
        ],
        "number_of_total_results": 1,
    }

    mock_client = MagicMock()
    mock_client.request = AsyncMock(
        return_value=ComicVineResponse(payload=mock_payload, from_cache=False, cache_key="test")
    )

    await search_comicvine_series(mock_client, "Batman")

    # The service passes params as the third positional argument.
    mock_client.request.assert_called_once()
    params = mock_client.request.call_args[0][2]
    assert isinstance(params, dict)
    field_list_used = params.get("field_list")
    assert field_list_used == EXPECTED_SEARCH_FIELD_LIST
    assert "image" in field_list_used  # Search results render cover thumbnails
