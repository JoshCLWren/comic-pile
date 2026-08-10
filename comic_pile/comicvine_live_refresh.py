"""Budgeted live ComicVine refresh for read-only hydration reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from comic_pile.comicvine_provider import ComicVineClient, ComicVineError, ComicVineRateLimitError


@dataclass(frozen=True)
class LiveRefreshSummary:
    """Summary of one live-refresh pass over a hydration report."""

    attempted: int
    matched: int
    failed: int
    budget_exhausted: bool


def _provider_issue_id(payload: Mapping[str, object]) -> int | None:
    """Extract the provider issue ID from a singular ComicVine response."""
    result = payload.get("results")
    if not isinstance(result, dict):
        return None
    value = result.get("id")
    return value if isinstance(value, int) else None


def _recount(report: dict[str, object]) -> None:
    """Recompute report status counts after live reconciliation."""
    issues = report.get("issues")
    if not isinstance(issues, list):
        return
    counts: dict[str, int] = {}
    for row in issues:
        if not isinstance(row, dict):
            continue
        status = row.get("status")
        if isinstance(status, str):
            counts[status] = counts.get(status, 0) + 1
    report["summary"] = {"total": len(issues), **counts}


async def refresh_confirmed_local_misses(
    report: dict[str, object],
    client: ComicVineClient,
    *,
    refresh: bool = False,
) -> LiveRefreshSummary:
    """Resolve confirmed local misses through the cached, endpoint-budgeted provider client.

    Only rows that already have an exact confirmed ComicVine issue identity are eligible. This
    deliberately avoids search or fuzzy matching. Cached successful responses are reused on reruns,
    and the provider client's persistent endpoint ledger survives process restarts.

    Args:
        report: Hydration report produced by ``build_report``.
        client: Configured ComicVine provider client.
        refresh: Force a live provider request instead of reusing a cached response.

    Returns:
        Counts describing the reconciliation pass. When the rolling endpoint budget is exhausted,
        processing stops cleanly and untouched rows remain resumable local misses.
    """
    issues = report.get("issues")
    if not isinstance(issues, list):
        raise ValueError("hydration report must contain an issues list")

    attempted = 0
    matched = 0
    failed = 0
    budget_exhausted = False

    for row in issues:
        if not isinstance(row, dict) or row.get("status") != "local-miss":
            continue
        issue_id = row.get("comicvine_issue_id")
        if not isinstance(issue_id, int):
            continue

        attempted += 1
        try:
            response = await client.fetch_issue(issue_id, refresh=refresh)
        except ComicVineRateLimitError:
            budget_exhausted = True
            break
        except ComicVineError as exc:
            row["status"] = "failed"
            row["provenance"] = "comicvine-live"
            row["detail"] = f"Confirmed identity live refresh failed: {exc}"
            failed += 1
            continue

        returned_id = _provider_issue_id(response.payload)
        if returned_id != issue_id:
            row["status"] = "failed"
            row["provenance"] = "comicvine-cache" if response.from_cache else "comicvine-live"
            row["detail"] = "Provider response did not match the confirmed ComicVine issue identity."
            failed += 1
            continue

        row["status"] = "matched"
        row["provenance"] = "comicvine-cache" if response.from_cache else "comicvine-live"
        row["detail"] = "Confirmed identity resolved through the budgeted ComicVine issue endpoint."
        matched += 1

    _recount(report)
    report["live_refresh"] = {
        "attempted": attempted,
        "matched": matched,
        "failed": failed,
        "budget_exhausted": budget_exhausted,
    }
    return LiveRefreshSummary(attempted, matched, failed, budget_exhausted)
