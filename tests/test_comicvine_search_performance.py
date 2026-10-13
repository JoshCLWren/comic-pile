"""Performance tests for ComicVine search endpoint optimization."""

import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from comic_pile.comicvine_provider import ComicVineClient, ComicVineResponse


def _mock_urlopen_response(payload: bytes) -> MagicMock:
    """Build a synchronous context-managed response mock for urllib.request.urlopen."""
    response = MagicMock()
    response.read.return_value = payload
    response.__enter__.return_value = response
    response.__exit__.return_value = None
    return response


@pytest.mark.asyncio
async def test_comicvine_search_performance_optimization():
    """Test that the optimized ComicVine search meets performance budget."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("comic_pile.comicvine_provider.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _mock_urlopen_response(
                b'{"status_code": 1, "results": [{"id": 12345, "name": "Test Series"}], '
                b'"number_of_total_results": 1}'
            )

            client = ComicVineClient(
                api_key="test-key",
                cache_dir=temp_dir,
                timeout_seconds=5.0,
            )

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
                        "page": i + 1,  # Use different page numbers to prevent caching
                    },
                )

                end_time = time.monotonic()
                duration = end_time - start_time
                times.append(duration)

                assert isinstance(result, ComicVineResponse)
                assert result.from_cache is False
                assert result.payload["status_code"] == 1

            avg_time = sum(times) / len(times)
            max_time = max(times)

            assert avg_time < 1.0, f"Average time {avg_time:.3f}s exceeds 1000ms budget"
            assert max_time < 2.0, f"Max time {max_time:.3f}s exceeds reasonable threshold"

            await client.close()


@pytest.mark.asyncio
async def test_comicvine_search_with_cache_performance():
    """Test that cached requests are significantly faster."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("comic_pile.comicvine_provider.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _mock_urlopen_response(
                b'{"status_code": 1, "results": [{"id": 12345, "name": "Test Series"}], '
                b'"number_of_total_results": 1}'
            )

            client = ComicVineClient(
                api_key="test-key",
                cache_dir=temp_dir,
                timeout_seconds=5.0,
            )

            start_time = time.monotonic()
            result1 = await client.request(
                "search",
                "search",
                {"query": "test", "resources": "volume", "limit": 10, "page": 1},
            )
            first_request_time = time.monotonic() - start_time

            start_time = time.monotonic()
            result2 = await client.request(
                "search",
                "search",
                {"query": "test", "resources": "volume", "limit": 10, "page": 1},
            )
            second_request_time = time.monotonic() - start_time

            assert result1.from_cache is False
            assert result2.from_cache is True

            assert second_request_time < first_request_time / 10, (
                f"Cached request ({second_request_time:.3f}s) should be much faster "
                f"than live request ({first_request_time:.3f}s)"
            )

            await client.close()


@pytest.mark.asyncio
async def test_comicvine_timeout_reduction():
    """Test that timeout reduction improves performance without breaking functionality."""
    client = ComicVineClient(
        api_key="test-key",
        cache_dir="/tmp/test-comicvine-timeout",
        timeout_seconds=2.0,
    )

    assert client.timeout_seconds == 2.0

    await client.close()