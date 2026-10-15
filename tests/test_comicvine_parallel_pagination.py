"""Tests for concurrent volume issue roster pagination in the ComicVine provider."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import NamedTuple
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.comicvine_resolution import get_comicvine_series_issues
from comic_pile.comicvine_provider import (
    COLLECTION_PAGE_LIMIT,
    VOLUME_ISSUES_PAGE_CONCURRENCY,
    ComicVineClient,
    ComicVineError,
    PersistentResourceThrottleTracker,
)

VOLUME_ID = 100


class _PageRequest(NamedTuple):
    """One observed provider request for the issue roster."""

    offset: int
    limit: int


def _client(cache_dir: Path) -> ComicVineClient:
    """Build a provider client backed by a disposable cache directory."""
    return ComicVineClient("secret", cache_dir)


def _row(issue_id: int, *, volume_id: int = VOLUME_ID) -> dict[str, object]:
    """Build one provider issue row for a volume."""
    return {
        "id": issue_id,
        "issue_number": str(issue_id),
        "name": f"Issue {issue_id}",
        "volume": {"id": volume_id},
    }


def _rows(start: int, stop: int) -> list[dict[str, object]]:
    """Build ordered provider rows with ids from start to stop inclusive."""
    return [_row(issue_id) for issue_id in range(start, stop + 1)]


def _tracker(path: Path, now: list[float]) -> PersistentResourceThrottleTracker:
    """Build a throttle tracker driven by a mutable fake clock."""
    return PersistentResourceThrottleTracker(path, clock=lambda: now[0])


def _roster_provider(
    total: int,
    *,
    page_sizes: dict[int, int] | None = None,
    observed: list[_PageRequest] | None = None,
    delay_seconds: float = 0.0,
) -> object:
    """Build a ``_request_sync`` replacement serving one volume roster.

    Args:
        total: ``number_of_total_results`` reported on every page.
        page_sizes: Explicit row count per offset, defaulting to a full roster.
        observed: Optional list that collects every page request.
        delay_seconds: Optional blocking delay inside each request.

    Returns:
        A synchronous request callable suitable for monkeypatching.
    """

    def provider(endpoint: str, params: object) -> dict[str, object]:
        assert endpoint == "issues"
        assert isinstance(params, dict)
        offset = int(params["offset"])
        limit = int(params["limit"])
        if observed is not None:
            observed.append(_PageRequest(offset=offset, limit=limit))
        if delay_seconds:
            time.sleep(delay_seconds)
        count = COLLECTION_PAGE_LIMIT if page_sizes is None else page_sizes.get(offset, 0)
        count = min(count, max(0, total - offset))
        first_id = offset + 1
        return {
            "status_code": 1,
            "number_of_total_results": total,
            "results": _rows(first_id, first_id + count - 1) if count else [],
        }

    return provider


@pytest.mark.asyncio
async def test_multi_page_roster_uses_one_request_per_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A multi-page roster must issue exactly the pages it needs and preserve order."""
    client = _client(tmp_path)
    observed: list[_PageRequest] = []
    monkeypatch.setattr(
        client,
        "_request_sync",
        _roster_provider(250, observed=observed),
    )

    rows = await client.fetch_volume_issues(VOLUME_ID, refresh=True)

    assert [row["id"] for row in rows] == list(range(1, 251))
    assert sorted((page.offset, page.limit) for page in observed) == [
        (0, COLLECTION_PAGE_LIMIT),
        (100, COLLECTION_PAGE_LIMIT),
        (200, COLLECTION_PAGE_LIMIT),
    ]


@pytest.mark.asyncio
async def test_single_page_roster_issues_exactly_one_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A roster that fits one page must not pay for a count probe."""
    client = _client(tmp_path)
    observed: list[_PageRequest] = []
    monkeypatch.setattr(
        client,
        "_request_sync",
        _roster_provider(12, observed=observed),
    )

    rows = await client.fetch_volume_issues(VOLUME_ID, refresh=True)

    assert len(rows) == 12
    assert observed == [_PageRequest(offset=0, limit=COLLECTION_PAGE_LIMIT)]


@pytest.mark.asyncio
async def test_roster_without_reported_total_returns_supplied_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing total must degrade to the returned rows rather than an empty roster."""
    client = _client(tmp_path)

    def provider(endpoint: str, params: object) -> dict[str, object]:
        return {"status_code": 1, "results": _rows(1, 3)}

    monkeypatch.setattr(client, "_request_sync", provider)

    rows = await client.fetch_volume_issues(VOLUME_ID, refresh=True)

    assert [row["id"] for row in rows] == [1, 2, 3]


@pytest.mark.asyncio
async def test_roster_tolerates_short_first_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A short first page ends the walk instead of requesting absent pages."""
    client = _client(tmp_path)
    observed: list[_PageRequest] = []
    monkeypatch.setattr(
        client,
        "_request_sync",
        _roster_provider(250, page_sizes={0: 40}, observed=observed),
    )

    rows = await client.fetch_volume_issues(VOLUME_ID, refresh=True)

    assert [row["id"] for row in rows] == list(range(1, 41))
    assert [page.offset for page in observed] == [0]


@pytest.mark.asyncio
async def test_roster_tolerates_later_page_count_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fewer rows than the reported total must not fail the whole roster."""
    client = _client(tmp_path)
    monkeypatch.setattr(
        client,
        "_request_sync",
        _roster_provider(250, page_sizes={0: 100, 100: 100, 200: 30}),
    )

    rows = await client.fetch_volume_issues(VOLUME_ID, refresh=True)

    assert [row["id"] for row in rows] == list(range(1, 231))


@pytest.mark.asyncio
async def test_remaining_pages_run_concurrently_within_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remaining pages overlap, but never more than the configured fan-out at once."""
    page_count = 12
    total = page_count * COLLECTION_PAGE_LIMIT
    client = _client(tmp_path)
    monkeypatch.setattr(
        client,
        "_request_sync",
        _roster_provider(total, delay_seconds=0.01),
    )

    in_flight = 0
    peak_in_flight = 0
    original_request = client.request

    async def tracked_request(*args: object, **kwargs: object):
        nonlocal in_flight, peak_in_flight
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        try:
            await asyncio.sleep(0)
            return await original_request(*args, **kwargs)
        finally:
            in_flight -= 1

    monkeypatch.setattr(client, "request", tracked_request)

    rows = await client.fetch_volume_issues(VOLUME_ID, refresh=True)

    assert len(rows) == total
    assert [row["id"] for row in rows] == list(range(1, total + 1))
    assert 2 <= peak_in_flight <= VOLUME_ISSUES_PAGE_CONCURRENCY


def test_reset_clears_a_cooldown_recorded_before_the_success(tmp_path: Path) -> None:
    """A cooldown older than the successful request still backs off normally."""
    now = [1001.0]
    tracker = _tracker(tmp_path / "throttle-state.json", now)
    tracker.set_cooldown("issues", now[0] + 300.0)

    tracker.reset("issues", observed_at=1002.0)

    assert tracker.get_cooldown("issues") is None


def test_reset_preserves_a_cooldown_recorded_by_a_concurrent_sibling(tmp_path: Path) -> None:
    """A sibling throttle observed during this request must survive its success."""
    now = [1000.0]
    tracker = _tracker(tmp_path / "throttle-state.json", now)
    tracker.set_cooldown("issues", now[0] + 300.0)

    now[0] = 1000.5
    tracker.reset("issues", observed_at=1000.0)

    cooldown = tracker.get_cooldown("issues")
    assert cooldown is not None
    assert cooldown.cooldown_until == 1300.0


@pytest.mark.asyncio
async def test_successful_page_does_not_clear_a_sibling_throttle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A parallel page success must not wipe the backoff a parallel page just recorded."""
    client = _client(tmp_path)

    def provider(endpoint: str, params: object) -> dict[str, object]:
        assert endpoint == "issues"
        assert isinstance(params, dict)
        client.throttle_tracker.set_cooldown("issues", time.time() + 300.0)
        return {"status_code": 1, "number_of_total_results": 1, "results": [_row(1)]}

    monkeypatch.setattr(client, "_request_sync", provider)

    rows = await client.fetch_volume_issues(VOLUME_ID, refresh=True)

    assert len(rows) == 1
    assert client.throttle_tracker.is_throttled("issues")


@pytest.mark.asyncio
async def test_service_overlaps_volume_metadata_with_roster() -> None:
    """Both provider reads must be in flight together rather than back to back."""
    mock_client = Mock()
    both_started = asyncio.Event()
    release = asyncio.Event()
    in_flight = 0

    async def fetch_volume(volume_id: int) -> Mock:
        nonlocal in_flight
        in_flight += 1
        if in_flight == 2:
            both_started.set()
        await release.wait()
        return Mock(payload={"results": {"id": VOLUME_ID, "name": "Test Series"}})

    async def fetch_volume_issues(volume_id: int) -> list[dict[str, object]]:
        nonlocal in_flight
        in_flight += 1
        if in_flight == 2:
            both_started.set()
        await release.wait()
        return [_row(1), _row(2)]

    mock_client.fetch_volume = fetch_volume
    mock_client.fetch_volume_issues = fetch_volume_issues

    pending = asyncio.ensure_future(
        get_comicvine_series_issues(mock_client, VOLUME_ID, series_name="")
    )
    try:
        await asyncio.wait_for(both_started.wait(), timeout=5.0)
    finally:
        release.set()
    result = await pending

    assert result.series_name == "Test Series"
    assert len(result.issues) == 2


@pytest.mark.asyncio
async def test_service_skips_volume_read_when_series_name_is_known() -> None:
    """A pre-resolved series name avoids the extra volume request entirely."""
    mock_client = Mock()
    mock_client.fetch_volume_issues = AsyncMock(return_value=[_row(1)])

    result = await get_comicvine_series_issues(
        mock_client, VOLUME_ID, series_name="Pre-fetched Series"
    )

    mock_client.fetch_volume.assert_not_called()
    mock_client.fetch_volume_issues.assert_called_once_with(VOLUME_ID)
    assert result.series_name == "Pre-fetched Series"
    assert len(result.issues) == 1


@pytest.mark.asyncio
async def test_service_keeps_issues_when_volume_metadata_fails() -> None:
    """A volume-metadata failure falls back to the generic label instead of dropping issues."""
    mock_client = Mock()
    mock_client.fetch_volume = AsyncMock(side_effect=ComicVineError("volume unavailable"))
    mock_client.fetch_volume_issues = AsyncMock(return_value=[_row(1), _row(2)])

    result = await get_comicvine_series_issues(mock_client, VOLUME_ID, series_name="")

    assert result.series_name == f"Volume {VOLUME_ID}"
    assert len(result.issues) == 2


@pytest.mark.asyncio
async def test_service_keeps_volume_metadata_when_roster_fails() -> None:
    """A roster failure still resolves the series name from the volume read."""
    mock_client = Mock()
    mock_client.fetch_volume = AsyncMock(
        return_value=Mock(payload={"results": {"id": VOLUME_ID, "name": "Test Series"}})
    )
    mock_client.fetch_volume_issues = AsyncMock(side_effect=ComicVineError("issues unavailable"))

    result = await get_comicvine_series_issues(mock_client, VOLUME_ID, series_name="")

    assert result.series_name == "Test Series"
    assert result.issues == []