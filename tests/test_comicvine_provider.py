"""Tests for endpoint-aware ComicVine hydration behavior."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from comic_pile.comicvine_provider import (
    COLLECTION_PAGE_LIMIT,
    ComicVineClient,
    ComicVineError,
    ComicVineRateLimitError,
    PersistentEndpointLimiter,
)


@pytest.mark.asyncio
async def test_request_reuses_successful_cache_without_spending_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rerun should use the successful raw cache rather than repeat provider I/O."""
    client = ComicVineClient("secret", tmp_path, requests_per_hour=1)
    calls: list[str] = []

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        calls.append(endpoint)
        return {"status_code": 1, "results": {"id": 99}}

    monkeypatch.setattr(client, "_request_sync", fake_request)

    first = await client.fetch_issue(99)
    second = await client.fetch_issue(99)

    assert first.from_cache is False
    assert second.from_cache is True
    assert calls == ["issue/4000-99"]
    ledger = json.loads((tmp_path / "request-ledger.json").read_text(encoding="utf-8"))
    assert len(ledger["issue"]) == 1
    cached_text = (tmp_path / "responses" / f"{first.cache_key}.json").read_text(encoding="utf-8")
    assert "secret" not in cached_text


def test_persistent_limiter_survives_restart(tmp_path: Path) -> None:
    """The rate ledger should remain authoritative across new limiter instances."""
    ledger = tmp_path / "ledger.json"
    first = PersistentEndpointLimiter(ledger, requests_per_hour=1, clock=lambda: 10000.0)
    first.acquire("issue")

    second = PersistentEndpointLimiter(ledger, requests_per_hour=1, clock=lambda: 10001.0)
    with pytest.raises(ComicVineRateLimitError):
        second.acquire("issue")


def test_persistent_limiter_drops_entries_outside_rolling_hour(tmp_path: Path) -> None:
    """Old requests should stop consuming endpoint capacity after one rolling hour."""
    ledger = tmp_path / "ledger.json"
    first = PersistentEndpointLimiter(ledger, requests_per_hour=1, clock=lambda: 10000.0)
    first.acquire("issues")

    later = PersistentEndpointLimiter(ledger, requests_per_hour=1, clock=lambda: 13601.0)
    later.acquire("issues")

    payload = json.loads(ledger.read_text(encoding="utf-8"))
    assert payload == {"issues": [13601.0]}


def test_provider_configuration_and_corrupt_cache_fail_safely(tmp_path: Path) -> None:
    """Reject invalid configuration while treating corrupt persisted cache data as a miss."""
    with pytest.raises(ValueError, match="requests_per_hour must be positive"):
        PersistentEndpointLimiter(tmp_path / "ledger.json", requests_per_hour=0)
    with pytest.raises(ValueError, match="api_key is required"):
        ComicVineClient(" ", tmp_path)

    client = ComicVineClient("secret", tmp_path)
    key = client._cache_key("issue/4000-1", {})
    cache_path = client._cache_path(key)
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("{not-json", encoding="utf-8")
    assert client._read_cache(key) is None

    ledger_path = tmp_path / "broken-ledger.json"
    ledger_path.write_text("[]", encoding="utf-8")
    limiter = PersistentEndpointLimiter(ledger_path)
    assert limiter._read() == {}


class FakeUrlResponse:
    """Minimal context-managed urllib response fixture."""

    def __init__(self, payload: bytes) -> None:
        """Store encoded response bytes."""
        self.payload = payload

    def __enter__(self) -> FakeUrlResponse:
        """Return the response fixture for a with block."""
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Leave the response fixture without suppressing exceptions."""

    def read(self) -> bytes:
        """Return encoded response bytes."""
        return self.payload


def test_request_sync_decodes_success_and_maps_provider_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decode successful provider JSON and convert HTTP/provider failures into typed errors."""
    client = ComicVineClient("secret", tmp_path)

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeUrlResponse(b'{"status_code": 1, "results": {"id": 7}}'),
    )
    assert client._request_sync("issue/4000-7", {})["results"] == {"id": 7}

    def rate_limited(request: object, timeout: float) -> FakeUrlResponse:
        raise urllib.error.HTTPError("https://example.invalid", 429, "slow down", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", rate_limited)
    with pytest.raises(ComicVineRateLimitError, match="HTTP 429"):
        client._request_sync("issue/4000-7", {})

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeUrlResponse(b'{"status_code": 100, "error": "bad key"}'),
    )
    with pytest.raises(ComicVineError, match="API error"):
        client._request_sync("issue/4000-7", {})


@pytest.mark.asyncio
async def test_deep_issue_uses_singular_relationship_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deep hydration should request relationships only from the singular issue endpoint."""
    client = ComicVineClient("secret", tmp_path)
    observed: list[tuple[str, object]] = []

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        observed.append((endpoint, params))
        return {
            "status_code": 1,
            "results": {
                "id": 42,
                "story_arc_credits": [{"id": 7, "name": "Annihilation"}],
                "person_credits": [{"id": 3, "name": "Writer", "role": "writer"}],
            },
        }

    monkeypatch.setattr(client, "_request_sync", fake_request)
    response = await client.fetch_issue(42)

    assert response.payload["results"]
    endpoint, params = observed[0]
    assert endpoint == "issue/4000-42"
    assert "story_arc_credits" in str(params)
    assert "person_credits" in str(params)


@pytest.mark.asyncio
async def test_volume_roster_paginates_at_documented_maximum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Volume hydration should page at 100 and preserve provider ordering."""
    client = ComicVineClient("secret", tmp_path)
    offsets: list[int] = []

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        assert endpoint == "issues"
        assert isinstance(params, dict)
        offset = int(params["offset"])
        offsets.append(offset)
        count = COLLECTION_PAGE_LIMIT if offset == 0 else 5
        return {
            "status_code": 1,
            "number_of_total_results": 105,
            "results": [
                {"id": offset + index, "issue_number": str(offset + index), "volume": {"id": 7}}
                for index in range(count)
            ],
        }

    monkeypatch.setattr(client, "_request_sync", fake_request)
    rows = await client.fetch_volume_issues(7, refresh=True)

    assert offsets == [0, 100]
    assert len(rows) == 105
    assert rows[0]["id"] == 0
    assert rows[-1]["id"] == 104


@pytest.mark.asyncio
async def test_volume_roster_rejects_ignored_provider_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful provider responses must still be validated for filter correctness."""
    client = ComicVineClient("secret", tmp_path)

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        return {
            "status_code": 1,
            "number_of_total_results": 1,
            "results": [{"id": 1, "issue_number": "1", "volume": {"id": 999}}],
        }

    monkeypatch.setattr(client, "_request_sync", fake_request)
    with pytest.raises(ComicVineError, match="ignored the requested volume filter"):
        await client.fetch_volume_issues(7, refresh=True)


@pytest.mark.asyncio
async def test_volume_roster_rejects_non_list_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject collection responses whose results payload is not a list."""
    client = ComicVineClient("secret", tmp_path)

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        return {"status_code": 1, "results": {"id": 1}}

    monkeypatch.setattr(client, "_request_sync", fake_request)
    with pytest.raises(ComicVineError, match="results list"):
        await client.fetch_volume_issues(7, refresh=True)


@pytest.mark.asyncio
async def test_fetch_volume_uses_singular_volume_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fetch a volume by the singular ComicVine volume resource path."""
    client = ComicVineClient("secret", tmp_path)
    observed: list[str] = []

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        observed.append(endpoint)
        return {"status_code": 1, "results": {"id": 7}}

    monkeypatch.setattr(client, "_request_sync", fake_request)
    response = await client.fetch_volume(7)

    assert response.payload["results"] == {"id": 7}
    assert observed == ["volume/4050-7"]


@pytest.mark.asyncio
async def test_story_arc_preserves_provider_membership_without_claiming_reading_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story-arc issue arrays should be retained verbatim rather than sorted as chapters."""
    client = ComicVineClient("secret", tmp_path)
    raw_members = [
        {"id": 2, "issue_number": "2"},
        {"id": 1, "issue_number": "1"},
    ]

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        return {"status_code": 1, "results": {"id": 8, "issues": raw_members}}

    monkeypatch.setattr(client, "_request_sync", fake_request)
    response = await client.fetch_story_arc(8)

    assert response.payload["results"] == {"id": 8, "issues": raw_members}
