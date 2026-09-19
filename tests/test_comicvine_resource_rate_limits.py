"""Regression coverage for ComicVine resource-level provider throttling."""

from __future__ import annotations

import urllib.error
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest

from comic_pile.comicvine_provider import (
    ComicVineClient,
    ComicVineRateLimitError,
    _retry_after_seconds,
)


def test_retry_after_parses_delta_seconds_and_http_date() -> None:
    """ComicVine may express Retry-After as seconds or an absolute HTTP date."""
    assert _retry_after_seconds({"Retry-After": "123"}, now=1000.0) == 123

    now = datetime(2026, 9, 19, 14, 0, tzinfo=timezone.utc)
    retry_at = now + timedelta(seconds=90)
    assert (
        _retry_after_seconds(
            {"Retry-After": format_datetime(retry_at, usegmt=True)},
            now=now.timestamp(),
        )
        == 90
    )


@pytest.mark.parametrize("status_code", [420, 429])
def test_http_throttle_exposes_resource_status_and_retry_after(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    """Provider throttle errors retain the resource and Retry-After metadata."""
    client = ComicVineClient("secret", tmp_path)

    def throttled(request: object, timeout: float) -> object:
        raise urllib.error.HTTPError(
            "https://example.invalid",
            status_code,
            "slow down",
            {"Retry-After": "75"},
            None,
        )

    monkeypatch.setattr("urllib.request.urlopen", throttled)

    with pytest.raises(ComicVineRateLimitError) as caught:
        client._request_sync("issue/4000-7", {})

    error = caught.value
    assert error.resource == "issue"
    assert error.status_code == status_code
    assert error.retry_after_seconds == 75
    assert "Retry-After=75s" in str(error)


@pytest.mark.asyncio
async def test_throttled_resource_does_not_block_other_resources_and_persists_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An /issue throttle must not disable /search, and its deadline survives restart."""
    client = ComicVineClient(
        "secret",
        tmp_path,
        minimum_live_request_interval_seconds=0,
    )
    calls: list[str] = []

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        calls.append(endpoint)
        if endpoint.startswith("issue/"):
            raise ComicVineRateLimitError(
                "ComicVine returned HTTP 420",
                resource="issue",
                status_code=420,
                retry_after_seconds=120,
            )
        return {"status_code": 1, "results": []}

    monkeypatch.setattr(client, "_request_sync", fake_request)

    with pytest.raises(ComicVineRateLimitError) as caught:
        await client.fetch_issue(7)
    assert caught.value.resource == "issue"

    search = await client.request("search", "search", {"query": "X-Men"})
    assert search.payload["results"] == []
    assert calls == ["issue/4000-7", "search"]

    restarted = ComicVineClient(
        "secret",
        tmp_path,
        minimum_live_request_interval_seconds=0,
    )
    restarted_calls: list[str] = []

    def should_not_call(endpoint: str, params: object) -> dict[str, object]:
        restarted_calls.append(endpoint)
        return {"status_code": 1, "results": {"id": 8}}

    monkeypatch.setattr(restarted, "_request_sync", should_not_call)
    with pytest.raises(ComicVineRateLimitError) as persisted:
        await restarted.fetch_issue(8)

    assert persisted.value.resource == "issue"
    assert persisted.value.retry_after_seconds is not None
    assert 0 < persisted.value.retry_after_seconds <= 120
    assert restarted_calls == []


@pytest.mark.asyncio
async def test_cached_response_is_usable_while_its_resource_is_throttled(tmp_path: Path) -> None:
    """Resource cooldowns guard provider calls, not already-cached successful responses."""
    client = ComicVineClient(
        "secret",
        tmp_path,
        minimum_live_request_interval_seconds=0,
    )
    params = {"field_list": "id"}
    key = client._cache_key("issue/4000-9", params)
    client._write_cache(key, {"status_code": 1, "results": {"id": 9}})
    client._block_resource("issue", 120)

    response = await client.request("issue", "issue/4000-9", params)

    assert response.from_cache is True
    assert response.payload["results"] == {"id": 9}


@pytest.mark.asyncio
async def test_throttle_without_retry_after_is_current_process_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing Retry-After blocks repeated calls now but does not poison future runs forever."""
    client = ComicVineClient(
        "secret",
        tmp_path,
        minimum_live_request_interval_seconds=0,
    )
    live_calls = 0

    def throttled(endpoint: str, params: object) -> dict[str, object]:
        nonlocal live_calls
        live_calls += 1
        raise ComicVineRateLimitError(
            "ComicVine returned HTTP 420",
            resource="issue",
            status_code=420,
        )

    monkeypatch.setattr(client, "_request_sync", throttled)
    with pytest.raises(ComicVineRateLimitError):
        await client.fetch_issue(10)
    with pytest.raises(ComicVineRateLimitError):
        await client.fetch_issue(11)
    assert live_calls == 1

    restarted = ComicVineClient(
        "secret",
        tmp_path,
        minimum_live_request_interval_seconds=0,
    )
    restarted_calls = 0

    def succeeds(endpoint: str, params: object) -> dict[str, object]:
        nonlocal restarted_calls
        restarted_calls += 1
        return {"status_code": 1, "results": {"id": 11}}

    monkeypatch.setattr(restarted, "_request_sync", succeeds)
    response = await restarted.fetch_issue(11)

    assert response.payload["results"] == {"id": 11}
    assert restarted_calls == 1
