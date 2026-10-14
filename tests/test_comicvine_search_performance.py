"""Transport coverage for the ComicVine client behind series search latency."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from comic_pile.comicvine_provider import (
    ComicVineClient,
    ComicVineError,
    ComicVineRateLimitError,
    get_shared_http_client,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _client_with_transport(
    handler: Handler,
    tmp_path: Path,
) -> tuple[ComicVineClient, httpx.AsyncClient]:
    """Build a client whose live requests are served by a mock transport."""
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )
    client = ComicVineClient("secret", tmp_path, http_client=http_client)
    return client, http_client


@pytest.mark.asyncio
async def test_httpx_transport_serves_live_search_payload(tmp_path: Path) -> None:
    """The injected async transport should decode live provider JSON payloads."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"status_code": 1, "results": [{"id": 1, "name": "Test"}]},
        )

    client, http_client = _client_with_transport(handler, tmp_path)
    try:
        response = await client.request(
            "search",
            "search",
            {"query": "test", "resources": "volume", "limit": 10, "page": 1},
        )
    finally:
        await http_client.aclose()

    assert response.from_cache is False
    assert response.payload["status_code"] == 1
    assert len(seen) == 1
    assert seen[0].url.path == "/api/search"
    assert seen[0].url.params["api_key"] == "secret"
    assert seen[0].url.params["format"] == "json"


@pytest.mark.asyncio
async def test_httpx_transport_follows_redirects(tmp_path: Path) -> None:
    """Redirect answers must be followed instead of surfacing as hard HTTP errors."""
    redirects: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "comicvine.gamespot.com":
            redirects.append(str(request.url))
            return httpx.Response(
                301,
                headers={"Location": "https://redirect.example.invalid/api/search"},
            )
        return httpx.Response(200, json={"status_code": 1, "results": []})

    client, http_client = _client_with_transport(handler, tmp_path)
    try:
        response = await client.request(
            "search",
            "search",
            {"query": "test", "resources": "volume", "limit": 10, "page": 1},
        )
    finally:
        await http_client.aclose()

    assert response.payload["results"] == []
    assert len(redirects) == 1


@pytest.mark.asyncio
async def test_httpx_transport_maps_rate_limit_and_http_errors(tmp_path: Path) -> None:
    """Throttle statuses become rate-limit errors; other HTTP failures stay typed errors."""
    client, http_client = _client_with_transport(
        lambda request: httpx.Response(
            429,
            headers={"Retry-After": "12"},
            json={"error": "slow down"},
        ),
        tmp_path,
    )
    try:
        with pytest.raises(ComicVineRateLimitError, match="HTTP 429") as throttled:
            await client.request("search", "search", {"query": "throttled", "page": 1})
    finally:
        await http_client.aclose()
    assert throttled.value.retry_after == 12.0

    client, http_client = _client_with_transport(
        lambda request: httpx.Response(500, json={"error": "boom"}),
        tmp_path,
    )
    try:
        with pytest.raises(ComicVineError, match="ComicVine HTTP 500 for search"):
            await client.request("search", "search", {"query": "broken", "page": 1})
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_httpx_transport_maps_provider_api_errors(tmp_path: Path) -> None:
    """Non-success provider status codes in the body surface as ComicVine errors."""
    client, http_client = _client_with_transport(
        lambda request: httpx.Response(200, json={"status_code": 100, "error": "Invalid API Key"}),
        tmp_path,
    )
    try:
        with pytest.raises(ComicVineError, match="ComicVine API error for search"):
            await client.request("search", "search", {"query": "unauthorized", "page": 1})
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_cached_response_skips_transport_entirely(tmp_path: Path) -> None:
    """A cached success should answer without spending another live transport call."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"status_code": 1, "results": [{"id": 7}]})

    client, http_client = _client_with_transport(handler, tmp_path)
    try:
        first = await client.request("search", "search", {"query": "cache", "page": 1})
        second = await client.request("search", "search", {"query": "cache", "page": 1})
    finally:
        await http_client.aclose()

    assert first.from_cache is False
    assert second.from_cache is True
    assert calls == ["/api/search"]
    cached_text = (tmp_path / "responses" / f"{first.cache_key}.json").read_text(encoding="utf-8")
    assert "secret" not in cached_text


@pytest.mark.asyncio
async def test_default_client_delegates_to_request_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an injected client, live requests keep using the urllib transport seam."""
    client = ComicVineClient("secret", tmp_path)
    calls: list[str] = []

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        calls.append(endpoint)
        return {"status_code": 1, "results": []}

    monkeypatch.setattr(client, "_request_sync", fake_request)

    response = await client.request("search", "search", {"query": "fallback", "page": 1})

    assert response.from_cache is False
    assert calls == ["search"]


def test_shared_http_client_reuses_one_redirect_following_client() -> None:
    """The shared production client is a singleton configured to follow redirects."""
    first = get_shared_http_client()
    second = get_shared_http_client()

    assert first is second
    assert first.follow_redirects is True
    assert first.timeout is not None


@pytest.mark.asyncio
async def test_httpx_transport_rejects_non_object_responses(tmp_path: Path) -> None:
    """Non-object provider payloads are rejected before callers parse them."""
    client, http_client = _client_with_transport(
        lambda request: httpx.Response(200, content=json.dumps(["not", "an", "object"]).encode()),
        tmp_path,
    )
    try:
        with pytest.raises(ComicVineError, match="non-object response"):
            await client.request("search", "search", {"query": "list", "page": 1})
    finally:
        await http_client.aclose()
