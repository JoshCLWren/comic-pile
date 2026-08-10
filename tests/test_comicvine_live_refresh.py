"""Tests for budgeted live refresh of ComicVine hydration misses."""

from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from comic_pile.comicvine_live_refresh import _recount, refresh_confirmed_local_misses
from comic_pile.comicvine_provider import (
    ComicVineError,
    ComicVineRateLimitError,
    ComicVineResponse,
)


def _report_with_misses() -> dict[str, object]:
    return {
        "summary": {"total": 3, "matched": 1, "local-miss": 2},
        "issues": [
            {"issue_id": 1, "status": "matched", "comicvine_issue_id": 101},
            {"issue_id": 2, "status": "local-miss", "comicvine_issue_id": 202},
            {"issue_id": 3, "status": "local-miss", "comicvine_issue_id": 303},
        ],
    }


def _issue_rows(report: dict[str, object]) -> list[dict[str, object]]:
    value = report["issues"]
    assert isinstance(value, list)
    assert all(isinstance(row, dict) for row in value)
    return cast(list[dict[str, object]], value)


async def test_refresh_batches_confirmed_misses_by_volume() -> None:
    """One volume roster can satisfy many confirmed misses without singular requests."""
    client = Mock()
    client.fetch_volume_issues = AsyncMock(
        return_value=[
            {"id": 202, "issue_number": "12", "volume": {"id": 500}},
            {"id": 303, "issue_number": "13", "volume": {"id": 500}},
        ]
    )
    client.fetch_issue = AsyncMock()
    report = _report_with_misses()
    rows = _issue_rows(report)
    rows[1]["comicvine_volume_id"] = 500
    rows[2]["comicvine_volume_id"] = 500

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.attempted == 2
    assert summary.matched == 2
    assert summary.volume_batches == 1
    assert summary.issue_requests == 0
    assert report["summary"] == {"total": 3, "matched": 3}
    assert rows[1]["provenance"] == "comicvine-volume-roster"
    assert rows[2]["provenance"] == "comicvine-volume-roster"
    client.fetch_volume_issues.assert_awaited_once_with(500, refresh=False)
    client.fetch_issue.assert_not_awaited()


async def test_volume_batch_preserves_identity_and_falls_back_narrowly() -> None:
    """A missing confirmed ID in a volume roster falls back to its singular issue lookup."""
    client = Mock()
    client.fetch_volume_issues = AsyncMock(
        return_value=[{"id": 202, "issue_number": "12", "volume": {"id": 500}}]
    )
    client.fetch_issue = AsyncMock(
        return_value=ComicVineResponse(
            payload={"results": {"id": 303}},
            from_cache=False,
            cache_key="issue-live",
        )
    )
    report = _report_with_misses()
    rows = _issue_rows(report)
    rows[1]["comicvine_volume_id"] = 500
    rows[2]["comicvine_volume_id"] = 500

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.matched == 2
    assert summary.volume_batches == 1
    assert summary.issue_requests == 1
    assert rows[2]["comicvine_issue_id"] == 303
    client.fetch_issue.assert_awaited_once_with(303, refresh=False)


async def test_volume_batch_failure_uses_singular_fallback() -> None:
    """A failed volume request does not strand confirmed identities that can use /issue."""
    client = Mock()
    client.fetch_volume_issues = AsyncMock(side_effect=ComicVineError("volume unavailable"))
    client.fetch_issue = AsyncMock(
        side_effect=[
            ComicVineResponse(
                payload={"results": {"id": 202}},
                from_cache=False,
                cache_key="issue-202",
            ),
            ComicVineResponse(
                payload={"results": {"id": 303}},
                from_cache=False,
                cache_key="issue-303",
            ),
        ]
    )
    report = _report_with_misses()
    rows = _issue_rows(report)
    rows[1]["comicvine_volume_id"] = 500
    rows[2]["comicvine_volume_id"] = 500

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.matched == 2
    assert summary.volume_batches == 0
    assert summary.issue_requests == 2
    assert client.fetch_issue.await_count == 2


async def test_volume_budget_exhaustion_preserves_resumable_rows() -> None:
    """Provider throttling during volume batching stops before spending another endpoint budget."""
    client = Mock()
    client.fetch_volume_issues = AsyncMock(
        side_effect=ComicVineRateLimitError("volume budget exhausted")
    )
    client.fetch_issue = AsyncMock()
    report = _report_with_misses()
    rows = _issue_rows(report)
    rows[1]["comicvine_volume_id"] = 500
    rows[2]["comicvine_volume_id"] = 500

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.budget_exhausted is True
    assert summary.attempted == 2
    assert summary.matched == 0
    assert summary.issue_requests == 0
    assert rows[1]["status"] == "local-miss"
    assert rows[2]["status"] == "local-miss"
    client.fetch_issue.assert_not_awaited()


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
    report = _report_with_misses()
    report["issues"] = _issue_rows(report)[:2]

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.matched == 1
    assert report["summary"] == {"total": 2, "matched": 2}
    refreshed = _issue_rows(report)[1]
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
    report = _report_with_misses()
    report["issues"] = _issue_rows(report)[:2]

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.failed == 1
    assert report["summary"] == {"total": 2, "matched": 1, "failed": 1}
    assert _issue_rows(report)[1]["status"] == "failed"
    assert _issue_rows(report)[1]["comicvine_issue_id"] == 202


async def test_refresh_rejects_malformed_provider_payload() -> None:
    """A singular response without an integer ID cannot satisfy a confirmed identity."""
    client = Mock()
    client.fetch_issue = AsyncMock(
        return_value=ComicVineResponse(
            payload={"results": "unexpected"},
            from_cache=False,
            cache_key="issue-live",
        )
    )
    report = _report_with_misses()
    report["issues"] = _issue_rows(report)[:2]

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.failed == 1
    assert _issue_rows(report)[1]["status"] == "failed"
    assert _issue_rows(report)[1]["comicvine_issue_id"] == 202


async def test_refresh_records_provider_failure_and_continues() -> None:
    """Provider failures become report rows while later confirmed misses remain resumable."""
    client = Mock()
    client.fetch_issue = AsyncMock(
        side_effect=[
            ComicVineError("provider unavailable"),
            ComicVineResponse(
                payload={"results": {"id": 303}},
                from_cache=False,
                cache_key="issue-live",
            ),
        ]
    )
    report = _report_with_misses()

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.attempted == 2
    assert summary.failed == 1
    assert summary.matched == 1
    rows = _issue_rows(report)
    assert rows[1]["status"] == "failed"
    assert rows[1]["provenance"] == "comicvine-live"
    assert rows[2]["status"] == "matched"


async def test_refresh_skips_ineligible_rows() -> None:
    """Only local misses with integer confirmed identities can spend provider budget."""
    client = Mock()
    client.fetch_issue = AsyncMock()
    report: dict[str, object] = {
        "issues": [
            "not-a-row",
            {"status": "matched", "comicvine_issue_id": 101},
            {"status": "local-miss", "comicvine_issue_id": "202"},
        ]
    }

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.attempted == 0
    assert report["summary"] == {"total": 3, "matched": 1, "local-miss": 1}
    client.fetch_issue.assert_not_awaited()


async def test_refresh_requires_issue_list() -> None:
    """Malformed hydration reports fail before any provider request is attempted."""
    client = Mock()
    client.fetch_issue = AsyncMock()

    with pytest.raises(ValueError, match="issues list"):
        await refresh_confirmed_local_misses({"issues": "invalid"}, client)

    client.fetch_issue.assert_not_awaited()


def test_recount_ignores_non_list_issue_payload() -> None:
    """Recount is a no-op when called on an unrelated report shape."""
    report: dict[str, object] = {"issues": "invalid", "summary": {"total": 1}}

    _recount(report)

    assert report["summary"] == {"total": 1}


async def test_budget_exhaustion_stops_cleanly_and_preserves_remaining_misses() -> None:
    """The rolling provider ceiling leaves untouched rows resumable on the next run."""
    client = Mock()
    client.fetch_issue = AsyncMock(side_effect=ComicVineRateLimitError("budget exhausted"))
    report = _report_with_misses()

    summary = await refresh_confirmed_local_misses(report, client)

    assert summary.budget_exhausted is True
    assert summary.attempted == 1
    assert summary.issue_requests == 1
    assert report["summary"] == {"total": 3, "matched": 1, "local-miss": 2}
    rows = _issue_rows(report)
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
    report = _report_with_misses()
    report["issues"] = _issue_rows(report)[:2]

    await refresh_confirmed_local_misses(report, client, refresh=True)

    client.fetch_issue.assert_awaited_once_with(202, refresh=True)
