"""Performance-shape tests for the ComicVine series search service path.

Latency for this route is dominated by the upstream provider call, so the
regression these tests guard is structural rather than clock-based: a search must
cost exactly one provider round trip, must ask for only the rendered fields, and
must never fan out a second request per returned row. Wall-clock bounds are
asserted in production telemetry instead (see the request-budget middleware),
not here, because a busy CI runner cannot time pure-Python post-processing
reliably.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.comicvine_resolution import (
    PROVIDER_SLOW_SEARCH_LOG_MS,
    search_comicvine_series,
)
from comic_pile.comicvine_provider import ComicVineResponse

EXPECTED_SEARCH_FIELD_LIST = (
    "id,name,publisher,start_year,count_of_issues,site_detail_url,image"
)
SLOW_SEARCH_LOGGER = "app.services.comicvine_resolution"


def _search_payload(*rows: dict[str, object], total: int | None = None) -> dict[str, object]:
    """Build a ComicVine /search payload with the requested rows."""
    payload: dict[str, object] = {"results": list(rows)}
    if total is not None:
        payload["number_of_total_results"] = total
    return payload


def _volume_row(volume_id: int, name: str, **overrides: object) -> dict[str, object]:
    """Build one realistic ComicVine volume row."""
    row: dict[str, object] = {
        "id": volume_id,
        "name": name,
        "publisher": {"name": "Marvel"},
        "start_year": "2000",
        "count_of_issues": "160",
        "site_detail_url": f"https://comicvine.gamespot.com/volume/4050-{volume_id}/",
        "image": {
            "medium_url": f"https://comicvine.gamespot.com/uploads/{volume_id}-medium.jpg",
            "small_url": f"https://comicvine.gamespot.com/uploads/{volume_id}-small.jpg",
        },
    }
    row.update(overrides)
    return row


def _mock_client(payload: dict[str, object], *, from_cache: bool = False) -> MagicMock:
    """Build a provider stub that answers every request with the same payload."""
    client = MagicMock()
    client.request = AsyncMock(
        return_value=ComicVineResponse(payload=payload, from_cache=from_cache, cache_key="test")
    )
    return client


def _requested_params(client: MagicMock) -> dict[str, object]:
    """Return the params dict of the single recorded provider call."""
    endpoint_bucket, endpoint, params = client.request.call_args[0]
    assert endpoint_bucket == "search"
    assert endpoint == "search"
    assert isinstance(params, dict)
    return params


@pytest.mark.asyncio
async def test_search_series_costs_one_provider_round_trip_per_call() -> None:
    """A search must never fan out a second provider request per returned row."""
    client = _mock_client(
        _search_payload(
            _volume_row(471, "Ultimate Spider-Man"),
            _volume_row(114402, "Ultimate Spider-Man 2024"),
            _volume_row(20870, "Spider-Man and His Amazing Friends"),
            total=4120,
        )
    )

    result = await search_comicvine_series(client, "spider-man", limit=3)

    client.request.assert_called_once()
    assert client.request.await_count == 1
    assert [row.name for row in result.results] == [
        "Ultimate Spider-Man",
        "Ultimate Spider-Man 2024",
        "Spider-Man and His Amazing Friends",
    ]


@pytest.mark.asyncio
async def test_search_series_requests_only_rendered_fields() -> None:
    """The search field list is the render contract; a cover thumbnail is part of it."""
    client = _mock_client(_search_payload(_volume_row(471, "Batman")))

    await search_comicvine_series(client, "Batman")

    params = _requested_params(client)
    field_list = params["field_list"]
    assert isinstance(field_list, str)
    assert field_list == EXPECTED_SEARCH_FIELD_LIST
    assert "image" in field_list
    assert params["query"] == "Batman"
    assert params["resources"] == "volume"


@pytest.mark.asyncio
async def test_search_series_clamps_page_size_to_the_provider_maximum() -> None:
    """An oversized caller limit is clamped so one page never exceeds the provider cap."""
    client = _mock_client(_search_payload(total=0))

    await search_comicvine_series(client, "Batman", limit=5000)

    params = _requested_params(client)
    assert params["limit"] == 100
    assert params["page"] == 1


@pytest.mark.asyncio
async def test_search_series_maps_provider_rows_without_extra_fetches() -> None:
    """Row mapping reads only the fields the search asked for, in one pass."""
    client = _mock_client(
        _search_payload(
            _volume_row(471, "Ultimate Spider-Man"),
            _volume_row(8, "Nam", publisher="Malibu", image=None),
            _volume_row(9, "Untyped publisher", publisher={"name": 7}),
            "not-a-row",
            {"id": "not-an-int", "name": "Skipped"},
            total=2,
        )
    )

    result = await search_comicvine_series(client, "Ultimate Spider-Man")

    client.request.assert_called_once()
    first = result.results[0]
    assert first.comicvine_volume_id == 471
    assert first.publisher == "Marvel"
    assert first.start_year == 2000
    assert first.issue_count == 160
    assert first.image_url == "https://comicvine.gamespot.com/uploads/471-medium.jpg"
    assert first.site_detail_url == "https://comicvine.gamespot.com/volume/4050-471/"
    assert [row.comicvine_volume_id for row in result.results] == [471, 8, 9]
    assert result.results[1].image_url is None
    assert result.results[2].publisher is None
    assert result.total_available == 2
    assert result.has_more is False
    assert result.next_offset is None


@pytest.mark.asyncio
async def test_search_series_skips_provider_call_without_a_query_or_client() -> None:
    """No client or blank query must not reach the provider at all."""
    client = _mock_client(_search_payload())

    blank = await search_comicvine_series(client, "   ")
    without_client = await search_comicvine_series(None, "Batman")

    client.request.assert_not_called()
    assert blank.results == []
    assert blank.has_more is False
    assert without_client.results == []


class _StubClock:
    """Monotonic stand-in that advances a fixed step on every read."""

    def __init__(self, step_seconds: float) -> None:
        self._step = step_seconds
        self._reads = 0

    def perf_counter(self) -> float:
        value = self._step * self._reads
        self._reads += 1
        return value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("elapsed_ms", "expects_warning"),
    [
        (PROVIDER_SLOW_SEARCH_LOG_MS + 1.0, True),
        (PROVIDER_SLOW_SEARCH_LOG_MS - 1.0, False),
    ],
)
async def test_search_series_warns_only_when_the_provider_phase_is_slow(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    elapsed_ms: float,
    expects_warning: bool,
) -> None:
    """The provider-phase warning fires above the threshold and stays silent below it."""
    monkeypatch.setattr(
        "app.services.comicvine_resolution.time", _StubClock(elapsed_ms / 1000.0)
    )
    client = _mock_client(_search_payload(_volume_row(471, "Batman")))

    with caplog.at_level(logging.WARNING, logger=SLOW_SEARCH_LOGGER):
        await search_comicvine_series(client, "Batman")

    warnings = [record for record in caplog.records if record.name == SLOW_SEARCH_LOGGER]
    assert bool(warnings) is expects_warning