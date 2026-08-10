"""Tests for budgeted live refresh of ComicVine hydration misses."""

from unittest.mock import AsyncMock, Mock

from comic_pile.comicvine_live_refresh import refresh_confirmed_local_misses
from comic_pile.comicvine_provider import ComicVineRateLimitError, ComicVineResponse


def report_with_misses() -> dict[str, object]:
    """Build a compact hydration report fixture."""
    return {
        "summary": {"total": 3, "matched": 1, "local-miss": 2},
        "issues": [
            {"issue_id": 1, "status": "matched", "comicvine_issue_id": 101},
            {"issue_id": 2, "status": "local-miss", "comicvine_issue_id": 202},
            {"issue_id": 3, "status": "local-miss", "comicvine_issue_id": 303},
        ],
    }


def issue_rows(report: dict[str, object]) -> list[dict[str, object]]:
    """Return typed issue rows from a report fixture."""
    value = report["issues"]
    assert isinstance(value, list)
    assert all(isinstance(row, dict) for row in value)
    return value


async def test_refresh_reconciles_confirmed_miss_from_cache() -> None:
    """Cached exact issue responses satisfy a local miss without spending new quota."""
    client = Mock()
    client.fetch_issue = AsyncMock(
        return_value=ComicVineResponse(
            payload={"results": {"id": 202, "issue_number": "12"}},
            from_cache=True,
            cache_key="issue-cached",
        )
    )
    report = report_with_misses()
    report["issues"] = issue_rows(report)[:2]

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.matched == 1
    assert report["summary"] == {"total": 2, "matched": 2}
    refreshed = issue_rows(report)[1]
    assert refreshed["provenance"] == "comicvine-cache"
    client.fetch_issue.assert_awaited_once_with(202, refresh=False)


async def test_refresh_rejects_provider_identity_mismatch() -> None:
    """A provider response may never replace the already-confirmed issue identity."""
    client = Mock()
    client.fetch_issue = AsyncMock(
        return_value=ComicVineResponse(
            payload={"results": {"id": 999}},
            from_cache=False,
            cache_key="issue-live",
        )
    )
    report = report_with_misses()
    report["issues"] = issue_rows(report)[:2]

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.failed == 1
    assert report["summary"] == {"total": 2, "matched": 1, "failed": 1}
    assert issue_rows(report)[1]["status"] == "failed"


async def test_budget_exhaustion_stops_cleanly_and_preserves_remaining_misses() -> None:
    """The rolling provider ceiling leaves untouched rows resumable on the next run."""
    client = Mock()
    client.fetch_issue = AsyncMock(side_effect=ComicVineRateLimitError("budget exhausted"))
    report = report_with_misses()

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.budget_exhausted is True
    assert summary.attempted == 1
    assert report["summary"] == {"total": 3, "matched": 1, "local-miss": 2}
    rows = issue_rows(report)
    assert rows[1]["status"] == "local-miss"
    assert rows[2]["status"] == "local-miss"
    live_refresh = report["live_refresh"]
    assert isinstance(live_refresh, dict)
    assert live_refresh["budget_exhausted"] is True


async def test_force_refresh_is_forwarded_to_provider_client() -> None:
    """Explicit refresh bypasses cached responses while preserving exact identity checks."""
    client = Mock()
    client.fetch_issue = AsyncMock(
        return_value=ComicVineResponse(
            payload={"results": {"id": 202}},
            from_cache=False,
            cache_key="issue-live",
        )
    )
    report = report_with_misses()
    report["issues"] = issue_rows(report)[:2]

    await refresh_confirmed_local_misses(report, client, refresh=True)

    client.fetch_issue.assert_awaited_once_with(202, refresh=True)
