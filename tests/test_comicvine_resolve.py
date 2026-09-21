"""Tests for direct ComicVine URL resolution in the correction flow."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.services.comicvine_resolution import resolve_comicvine_input
from comic_pile.comicvine_provider import ComicVineError, ComicVineResponse


@dataclass
class FakeResolveClient:
    """ComicVine client stand-in with canned singular/collection payloads."""

    issue_results: dict[str, object] | None = field(default_factory=dict)
    volume_results: dict[str, object] | None = field(default_factory=dict)
    issue_rows: list[dict[str, object]] = field(default_factory=list)
    issue_error: Exception | None = None
    volume_error: Exception | None = None
    requests: list[str] = field(default_factory=list)

    async def fetch_issue(self, issue_id: int, *, refresh: bool = False) -> ComicVineResponse:
        """Fetch a single ComicVine issue by ID."""
        self.requests.append(f"issue:{issue_id}")
        if self.issue_error is not None:
            raise self.issue_error
        return ComicVineResponse(
            payload={"results": self.issue_results or {}},
            from_cache=True,
            cache_key="issue",
        )

    async def fetch_volume(self, volume_id: int, *, refresh: bool = False) -> ComicVineResponse:
        """Fetch a single ComicVine volume by ID."""
        self.requests.append(f"volume:{volume_id}")
        if self.volume_error is not None:
            raise self.volume_error
        return ComicVineResponse(
            payload={"results": self.volume_results or {}},
            from_cache=True,
            cache_key="volume",
        )

    async def fetch_volume_issues(
        self, volume_id: int, *, refresh: bool = False
    ) -> list[dict[str, object]]:
        """Fetch all issues belonging to a ComicVine volume."""
        self.requests.append(f"issues:{volume_id}")
        return list(self.issue_rows)


def _issue_result() -> dict[str, object]:
    return {
        "id": 1154070,
        "name": "I, Superman",
        "issue_number": "34",
        "cover_date": "2023-09-01",
        "store_date": "2023-09-13",
        "image": {"small_url": "https://img.example/1154070-small.jpg"},
        "volume": {"id": 148476, "name": "Superman"},
    }


def _volume_result() -> dict[str, object]:
    return {
        "id": 148476,
        "name": "Superman",
        "publisher": {"name": "DC Comics"},
        "start_year": 2023,
        "count_of_issues": 22,
        "image": {"small_url": "https://img.example/148476-small.jpg"},
    }


@pytest.mark.asyncio
async def test_resolve_issue_url_returns_exact_issue() -> None:
    """An issue URL resolves directly to the exact ComicVine issue."""
    client = FakeResolveClient(issue_results=_issue_result())

    response = await resolve_comicvine_input(
        client, "https://comicvine.gamespot.com/superman-34-i-superman/4000-1154070/"
    )

    assert response.kind == "issue"
    assert response.validation_error is None
    assert response.issue is not None
    assert response.issue.comicvine_issue_id == 1154070
    assert response.issue.series_name == "Superman"
    assert response.issue.volume_id == 148476
    assert response.issue.issue_number == "34"
    assert response.issue.name == "I, Superman"
    assert response.issue.cover_date == "2023-09-01"
    assert response.issue.image_url == "https://img.example/1154070-small.jpg"
    assert client.requests == ["issue:1154070"]


@pytest.mark.asyncio
async def test_resolve_volume_url_returns_volume_and_issues() -> None:
    """A volume URL resolves to the volume and its issue list."""
    client = FakeResolveClient(
        volume_results=_volume_result(),
        issue_rows=[
            {"id": 1001, "issue_number": "1", "name": None, "cover_date": "2023-01-01"},
            {"id": 1002, "issue_number": "34", "name": "I, Superman"},
        ],
    )

    response = await resolve_comicvine_input(
        client, "https://comicvine.gamespot.com/superman/4050-148476/"
    )

    assert response.kind == "volume"
    assert response.validation_error is None
    assert response.volume is not None
    assert response.volume.comicvine_volume_id == 148476
    assert response.volume.name == "Superman"
    assert response.volume.publisher == "DC Comics"
    assert response.volume.start_year == 2023
    assert response.volume.issue_count == 22
    assert [issue.comicvine_issue_id for issue in response.issues] == [1001, 1002]


@pytest.mark.asyncio
async def test_resolve_plain_text_returns_search() -> None:
    """Plain text without a URL is classified as a search."""
    response = await resolve_comicvine_input(
        FakeResolveClient(), "Ultimate Spider-Man"
    )

    assert response.kind == "search"
    assert response.validation_error is None
    assert response.issue is None
    assert response.volume is None


@pytest.mark.asyncio
async def test_resolve_unknown_host_returns_validation_error() -> None:
    """A URL from an unknown host returns a validation error."""
    response = await resolve_comicvine_input(
        FakeResolveClient(), "https://comicvine.example.com/superman/4050-148476/"
    )

    assert response.kind == "search"
    assert response.validation_error is not None
    assert "comicvine.gamespot.com" in response.validation_error


@pytest.mark.asyncio
async def test_resolve_unsupported_resource_returns_validation_error() -> None:
    """An unsupported resource prefix returns a validation error."""
    response = await resolve_comicvine_input(
        FakeResolveClient(), "https://comicvine.gamespot.com/arc/4045-12345/"
    )

    assert response.kind == "search"
    assert response.validation_error is not None


@pytest.mark.asyncio
async def test_resolve_provider_failure_is_safe() -> None:
    """Provider failure returns a validation error without mutating identity."""
    client = FakeResolveClient(issue_error=ComicVineError("provider down"))

    response = await resolve_comicvine_input(
        client, "https://comicvine.gamespot.com/x/4000-1154070/"
    )

    assert response.kind == "issue"
    assert response.validation_error is not None
    assert response.issue is None
    assert client.requests == ["issue:1154070"]


@pytest.mark.asyncio
async def test_resolve_volume_provider_failure_is_safe() -> None:
    """Volume provider failure returns a validation error."""
    client = FakeResolveClient(volume_error=ComicVineError("provider down"))

    response = await resolve_comicvine_input(
        client, "https://comicvine.gamespot.com/superman/4050-148476/"
    )

    assert response.kind == "volume"
    assert response.validation_error is not None
    assert response.volume is None


@pytest.mark.asyncio
async def test_resolve_without_client_returns_validation_error() -> None:
    """A pasted issue URL with no configured client returns a validation error."""
    response = await resolve_comicvine_input(
        None, "https://comicvine.gamespot.com/superman/4050-148476/"
    )

    assert response.kind == "volume"
    assert response.validation_error is not None