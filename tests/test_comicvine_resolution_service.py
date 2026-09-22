"""Service-level tests for ComicVine series search disambiguation metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from app.services.comicvine_resolution import search_comicvine_series
from comic_pile.comicvine_provider import ComicVineResponse


@dataclass
class FakeSearchClient:
    """Minimal ComicVine client stand-in returning one canned search payload."""

    payload: dict[str, object]
    requests: list[dict[str, object]] = field(default_factory=list)

    async def request(
        self,
        endpoint_bucket: str,
        endpoint: str,
        params: Mapping[str, object],
        *,
        refresh: bool = False,
    ) -> ComicVineResponse:
        """Record the request parameters and return the canned payload.

        Args:
            endpoint_bucket: Stable rate-limit bucket for the provider path.
            endpoint: Relative API path.
            params: Provider request parameters.
            refresh: Force a live request instead of a cached payload.

        Returns:
            The canned provider response.
        """
        self.requests.append(dict(params))
        return ComicVineResponse(payload=self.payload, from_cache=False, cache_key="test")


@pytest.mark.asyncio
async def test_search_series_requests_disambiguation_fields() -> None:
    """Search must request start year and issue count so same-title results differ."""
    client = FakeSearchClient(payload={"results": []})

    await search_comicvine_series(client, "Ultimate Spider-Man")

    assert len(client.requests) == 1
    field_list = client.requests[0]["field_list"]
    assert isinstance(field_list, str)
    assert "start_year" in field_list
    assert "count_of_issues" in field_list


@pytest.mark.asyncio
async def test_search_series_parses_string_start_year_and_issue_count() -> None:
    """ComicVine returns start_year as a string; it must still reach the UI."""
    client = FakeSearchClient(
        payload={
            "results": [
                {
                    "id": 471,
                    "name": "Ultimate Spider-Man",
                    "publisher": {"name": "Marvel"},
                    "start_year": "2000",
                    "count_of_issues": "160",
                    "image": {"medium_url": "https://img.example/471-medium.jpg"},
                }
            ],
            "number_of_total_results": 1,
        }
    )

    response = await search_comicvine_series(client, "Ultimate Spider-Man")

    result = response.results[0]
    assert result.start_year == 2000
    assert result.issue_count == 160
    assert result.publisher == "Marvel"
    assert result.image_url == "https://img.example/471-medium.jpg"


@pytest.mark.asyncio
async def test_search_series_same_title_volumes_stay_distinguishable() -> None:
    """Two same-title volumes must expose differing human metadata to the caller."""
    client = FakeSearchClient(
        payload={
            "results": [
                {
                    "id": 471,
                    "name": "Ultimate Spider-Man",
                    "publisher": {"name": "Marvel"},
                    "start_year": "2000",
                    "count_of_issues": 160,
                },
                {
                    "id": 114402,
                    "name": "Ultimate Spider-Man",
                    "publisher": {"name": "Marvel"},
                    "start_year": "2024",
                    "count_of_issues": 18,
                },
            ],
            "number_of_total_results": 2,
        }
    )

    response = await search_comicvine_series(client, "Ultimate Spider-Man")

    assert len(response.results) == 2
    first, second = response.results
    assert first.comicvine_volume_id != second.comicvine_volume_id
    assert (first.start_year, first.issue_count) != (second.start_year, second.issue_count)


@pytest.mark.asyncio
async def test_search_series_tolerates_non_numeric_metadata() -> None:
    """Non-numeric year/count values degrade to None instead of crashing or lying."""
    client = FakeSearchClient(
        payload={
            "results": [
                {
                    "id": 42,
                    "name": "Stormwatch",
                    "publisher": "WildStorm",
                    "start_year": "unknown",
                    "count_of_issues": None,
                }
            ],
            "number_of_total_results": 1,
        }
    )

    response = await search_comicvine_series(client, "Stormwatch")

    result = response.results[0]
    assert result.start_year is None
    assert result.issue_count is None


@pytest.mark.asyncio
async def test_search_series_passes_page_and_reports_paging_metadata() -> None:
    """Search maps a 0-based offset to a 1-based provider page and exposes a next page."""
    client = FakeSearchClient(
        payload={
            "results": [
                {"id": 100 + n, "name": f"Series {n}"} for n in range(10)
            ],
            "number_of_total_results": 27,
        }
    )

    response = await search_comicvine_series(client, "Superman", limit=10, offset=10)

    # offset=10 with limit=10 is the second page (1-based page=2), not page 11.
    assert client.requests[0]["page"] == 2
    assert "offset" not in client.requests[0]
    assert client.requests[0]["limit"] == 10
    assert response.offset == 10
    assert response.limit == 10
    assert response.total_available == 27
    assert response.has_more is True
    assert response.next_offset == 20


@pytest.mark.asyncio
async def test_search_series_final_page_has_no_next_offset() -> None:
    """When everything is loaded has_more is False and next_offset is None."""
    client = FakeSearchClient(
        payload={
            "results": [{"id": 200 + n, "name": f"Series {n}"} for n in range(3)],
            "number_of_total_results": 13,
        }
    )

    response = await search_comicvine_series(client, "X-Men", limit=10, offset=10)

    assert response.offset == 10
    assert len(response.results) == 3
    assert response.next_offset is None
    assert response.has_more is False


@pytest.mark.asyncio
async def test_search_series_clamps_negative_offset_and_limit() -> None:
    """Offsets and limits are clamped to the provider contract."""
    client = FakeSearchClient(payload={"results": [], "number_of_total_results": 0})

    response = await search_comicvine_series(client, "Spider-Man", limit=-5, offset=-3)

    # Clamped offset=0 with limit=1 is the first page (1-based page=1).
    assert client.requests[0]["page"] == 1
    assert "offset" not in client.requests[0]
    assert client.requests[0]["limit"] == 1
    assert response.offset == 0
    assert response.limit == 1


@pytest.mark.asyncio
async def test_search_series_maps_each_offset_bucket_to_correct_page() -> None:
    """Offsets must map to the enclosing limit bucket, not to raw 1-based rows.

    offset=10 with limit=10 is page 2 (results 11-20). Mapping it to page=11
    would skip results 11-100 and dead-end Load more for modest result counts.
    """
    client = FakeSearchClient(
        payload={
            "results": [{"id": 3000 + n, "name": f"Series {n}"} for n in range(10)],
            "number_of_total_results": 45,
        }
    )

    response = await search_comicvine_series(client, "Batman", limit=10, offset=10)

    assert client.requests[0]["page"] == 2
    assert client.requests[0]["limit"] == 10
    assert response.offset == 10
    assert response.next_offset == 20

    client2 = FakeSearchClient(
        payload={
            "results": [{"id": 4000 + n, "name": f"Series {n}"} for n in range(10)],
            "number_of_total_results": 45,
        }
    )

    await search_comicvine_series(client2, "Batman", limit=10, offset=35)

    assert client2.requests[0]["page"] == 4


@pytest.mark.asyncio
async def test_search_series_uses_page_parameter_instead_of_offset() -> None:
    """ComicVine search API should receive page (1-based) instead of offset (0-based)."""
    client = FakeSearchClient(
        payload={
            "results": [
                {"id": 1000 + n, "name": f"Page 1 Series {n}"} for n in range(10)
            ],
            "number_of_total_results": 25,
        }
    )

    response = await search_comicvine_series(client, "Batman", limit=10, offset=10)

    # offset=10 with limit=10 is the second page (1-based page=2), not page 11.
    assert client.requests[0]["page"] == 2
    assert "offset" not in client.requests[0]
    assert client.requests[0]["limit"] == 10
    assert response.offset == 10
    assert response.limit == 10
    assert response.total_available == 25
    assert response.has_more is True
    assert response.next_offset == 20


@pytest.mark.asyncio
async def test_search_series_different_pages_return_different_results() -> None:
    """Load more should append new comicvine_volume_id IDs, not repeat page 1 results."""
    page1_client = FakeSearchClient(
        payload={
            "results": [
                {"id": 1000 + n, "name": f"Series {n}"} for n in range(10)
            ],
            "number_of_total_results": 25,
        }
    )

    page2_client = FakeSearchClient(
        payload={
            "results": [
                {"id": 2000 + n, "name": f"Series {n}"} for n in range(10)
            ],
            "number_of_total_results": 25,
        }
    )

    # First page (offset=0 -> page=1)
    response1 = await search_comicvine_series(
        page1_client, "Ultimate Spider-Man", limit=10, offset=0
    )

    # Second page (offset=10 -> page=2)
    response2 = await search_comicvine_series(
        page2_client, "Ultimate Spider-Man", limit=10, offset=10
    )

    # Verify different pages return different IDs
    page1_ids = {result.comicvine_volume_id for result in response1.results}
    page2_ids = {result.comicvine_volume_id for result in response2.results}

    assert page1_ids.isdisjoint(page2_ids), "Page 1 and Page 2 should have different volume IDs"
    assert min(page2_ids) > max(page1_ids), "Page 2 IDs should be higher than Page 1 IDs"
    assert page1_client.requests[0]["page"] == 1
    assert page2_client.requests[0]["page"] == 2

    # Verify pagination metadata works correctly
    assert response1.has_more is True
    assert response1.next_offset == 10
    assert response2.has_more is True
    assert response2.next_offset == 20


@pytest.mark.asyncio
async def test_search_series_without_metadata_does_not_claim_more_pages() -> None:
    """Without a total count the provider cannot promise additional pages."""
    client = FakeSearchClient(
        payload={
            "results": [{"id": 300 + n, "name": f"Series {n}"} for n in range(10)],
        }
    )

    response = await search_comicvine_series(client, "Series", limit=10, offset=0)

    assert response.total_available == 10
    assert response.has_more is False
    assert response.next_offset is None
