"""Service-level tests for ComicVine series search disambiguation metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

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
