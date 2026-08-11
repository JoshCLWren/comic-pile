"""Tests for optional deep ComicVine issue and story-arc hydration."""

from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from comic_pile.comicvine_deep_hydration import hydrate_deep_metadata
from comic_pile.comicvine_provider import (
    ComicVineError,
    ComicVineRateLimitError,
    ComicVineResponse,
)


def _report() -> dict[str, object]:
    return {
        "issues": [
            {"issue_id": 1, "status": "matched", "comicvine_issue_id": 101},
            {"issue_id": 2, "status": "matched", "comicvine_issue_id": 202},
            {"issue_id": 3, "status": "unresolved", "comicvine_issue_id": None},
        ]
    }


def _rows(report: dict[str, object]) -> list[dict[str, object]]:
    issues = report["issues"]
    assert isinstance(issues, list)
    assert all(isinstance(row, dict) for row in issues)
    return cast(list[dict[str, object]], issues)


async def test_deep_hydration_attaches_metadata_without_changing_identity_status() -> None:
    """Deep metadata remains report-only and preserves the matched identity state."""
    client = Mock()
    client.fetch_issue = AsyncMock(
        side_effect=[
            ComicVineResponse(
                payload={"results": {"id": 101, "name": "One", "story_arc_credits": []}},
                from_cache=True,
                cache_key="issue-101",
            ),
            ComicVineResponse(
                payload={"results": {"id": 202, "name": "Two", "story_arc_credits": []}},
                from_cache=False,
                cache_key="issue-202",
            ),
        ]
    )
    client.fetch_story_arc = AsyncMock()
    report = _report()

    summary = await hydrate_deep_metadata(report, client)

    assert summary.hydrated_issues == 2
    assert summary.attempted_issues == 2
    rows = _rows(report)
    assert rows[0]["status"] == "matched"
    assert rows[0]["comicvine_issue_id"] == 101
    assert rows[0]["deep_hydration"] == {
        "status": "hydrated",
        "provenance": "comicvine-cache",
        "metadata": {"id": 101, "name": "One", "story_arc_credits": []},
    }
    assert rows[1]["deep_hydration"]["provenance"] == "comicvine-live"
    client.fetch_story_arc.assert_not_awaited()


async def test_story_arc_hydration_deduplicates_ids_across_issues() -> None:
    """An arc credited by multiple issues is fetched only once after issue hydration."""
    client = Mock()
    client.fetch_issue = AsyncMock(
        side_effect=[
            ComicVineResponse(
                payload={
                    "results": {
                        "id": 101,
                        "story_arc_credits": [{"id": 9001}, {"id": 9002}],
                    }
                },
                from_cache=False,
                cache_key="issue-101",
            ),
            ComicVineResponse(
                payload={
                    "results": {
                        "id": 202,
                        "story_arc_credits": [{"id": 9001}, {"id": 9001}],
                    }
                },
                from_cache=False,
                cache_key="issue-202",
            ),
        ]
    )
    client.fetch_story_arc = AsyncMock(
        side_effect=[
            ComicVineResponse(
                payload={"results": {"id": 9001, "name": "Arc One"}},
                from_cache=False,
                cache_key="arc-9001",
            ),
            ComicVineResponse(
                payload={"results": {"id": 9002, "name": "Arc Two"}},
                from_cache=True,
                cache_key="arc-9002",
            ),
        ]
    )
    report = _report()

    summary = await hydrate_deep_metadata(report, client, hydrate_story_arcs=True)

    assert summary.discovered_story_arcs == 2
    assert summary.hydrated_story_arcs == 2
    assert client.fetch_story_arc.await_count == 2
    client.fetch_story_arc.assert_any_await(9001, refresh=False)
    client.fetch_story_arc.assert_any_await(9002, refresh=False)
    assert set(cast(dict[str, object], report["story_arcs"])) == {"9001", "9002"}


async def test_deep_hydration_rejects_identity_mismatch() -> None:
    """Deep hydration never replaces or accepts a mismatched confirmed issue identity."""
    client = Mock()
    client.fetch_issue = AsyncMock(
        side_effect=[
            ComicVineResponse(
                payload={"results": {"id": 999}},
                from_cache=False,
                cache_key="issue-101",
            ),
            ComicVineResponse(
                payload={"results": {"id": 202}},
                from_cache=False,
                cache_key="issue-202",
            ),
        ]
    )
    client.fetch_story_arc = AsyncMock()
    report = _report()

    summary = await hydrate_deep_metadata(report, client)

    assert summary.failed_issues == 1
    first = _rows(report)[0]
    assert first["status"] == "matched"
    assert first["comicvine_issue_id"] == 101
    assert first["deep_hydration"]["status"] == "failed"


async def test_issue_budget_exhaustion_preserves_unattempted_rows() -> None:
    """Issue endpoint throttling stops cleanly so a rerun can resume from cache/report state."""
    client = Mock()
    client.fetch_issue = AsyncMock(side_effect=ComicVineRateLimitError("issue budget exhausted"))
    client.fetch_story_arc = AsyncMock()
    report = _report()

    summary = await hydrate_deep_metadata(report, client, hydrate_story_arcs=True)

    assert summary.issue_budget_exhausted is True
    assert summary.attempted_issues == 1
    assert summary.hydrated_issues == 0
    assert "deep_hydration" not in _rows(report)[1]
    client.fetch_story_arc.assert_not_awaited()


async def test_story_arc_budget_exhaustion_is_independent_of_issue_budget() -> None:
    """Story-arc throttling preserves completed issue metadata and stops only arc requests."""
    client = Mock()
    client.fetch_issue = AsyncMock(
        side_effect=[
            ComicVineResponse(
                payload={"results": {"id": 101, "story_arc_credits": [{"id": 9001}]}},
                from_cache=False,
                cache_key="issue-101",
            ),
            ComicVineResponse(
                payload={"results": {"id": 202, "story_arc_credits": [{"id": 9002}]}},
                from_cache=False,
                cache_key="issue-202",
            ),
        ]
    )
    client.fetch_story_arc = AsyncMock(
        side_effect=ComicVineRateLimitError("story arc budget exhausted")
    )
    report = _report()

    summary = await hydrate_deep_metadata(report, client, hydrate_story_arcs=True)

    assert summary.hydrated_issues == 2
    assert summary.story_arc_budget_exhausted is True
    assert summary.hydrated_story_arcs == 0
    assert client.fetch_story_arc.await_count == 1


async def test_provider_failure_is_recorded_without_aborting_later_issues() -> None:
    """A single provider error is reportable while later issues continue."""
    client = Mock()
    client.fetch_issue = AsyncMock(
        side_effect=[
            ComicVineError("provider unavailable"),
            ComicVineResponse(
                payload={"results": {"id": 202}},
                from_cache=False,
                cache_key="issue-202",
            ),
        ]
    )
    client.fetch_story_arc = AsyncMock()
    report = _report()

    summary = await hydrate_deep_metadata(report, client)

    assert summary.failed_issues == 1
    assert summary.hydrated_issues == 1
    assert _rows(report)[0]["deep_hydration"]["status"] == "failed"
    assert _rows(report)[1]["deep_hydration"]["status"] == "hydrated"


async def test_malformed_report_fails_before_provider_calls() -> None:
    """Deep hydration rejects malformed report shapes before spending provider budget."""
    client = Mock()
    client.fetch_issue = AsyncMock()
    client.fetch_story_arc = AsyncMock()

    with pytest.raises(ValueError, match="issues list"):
        await hydrate_deep_metadata({"issues": "invalid"}, client)

    client.fetch_issue.assert_not_awaited()
    client.fetch_story_arc.assert_not_awaited()
