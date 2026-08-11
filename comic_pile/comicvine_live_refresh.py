"""Budgeted live ComicVine refresh for read-only hydration reports."""

from __future__ import annotations

from collections import defaultdict
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
    volume_batches: int
    issue_requests: int


def _provider_issue_id(payload: Mapping[str, object]) -> int | None:
    """Extract the provider issue ID from a singular ComicVine response."""
    result = payload.get("results")
    if not isinstance(result, dict):
        return None
    value = result.get("id")
    return value if isinstance(value, int) else None


def _volume_issue_ids(rows: list[dict[str, object]]) -> set[int]:
    """Return integer issue IDs from one validated ComicVine volume roster."""
    issue_ids: set[int] = set()
    for row in rows:
        value = row.get("id")
        if isinstance(value, int):
            issue_ids.add(value)
    return issue_ids


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


def _mark_matched(row: dict[str, object], *, provenance: str, detail: str) -> None:
    """Mark one hydration row as safely reconciled without replacing its identity."""
    row["status"] = "matched"
    row["provenance"] = provenance
    row["detail"] = detail


def _mark_failed(row: dict[str, object], *, provenance: str, detail: str) -> None:
    """Mark one hydration row failed while preserving its confirmed identity."""
    row["status"] = "failed"
    row["provenance"] = provenance
    row["detail"] = detail


async def refresh_confirmed_local_misses(
    report: dict[str, object],
    client: ComicVineClient,
    *,
    refresh: bool = False,
) -> LiveRefreshSummary:
    """Resolve confirmed local misses through cached, endpoint-budgeted provider calls.

    Rows that carry a known ComicVine volume ID are grouped first so one paginated ``/issues``
    request sequence can reconcile many confirmed issue IDs. Any rows not satisfied by their volume
    roster then fall back to the narrow singular issue endpoint. Exact confirmed issue identities
    remain authoritative throughout; volume membership is only a batching optimization and never
    replaces or guesses an issue identity.

    Args:
        report: Hydration report produced by ``build_report`` or an enriched assessment report.
        client: Configured ComicVine provider client.
        refresh: Force live provider requests instead of reusing cached responses.

    Returns:
        Counts describing the reconciliation pass. When a rolling endpoint budget is exhausted,
        untouched rows remain local misses so a later rerun can resume safely.
    """
    issues = report.get("issues")
    if not isinstance(issues, list):
        raise ValueError("hydration report must contain an issues list")

    eligible = [
        row
        for row in issues
        if isinstance(row, dict)
        and row.get("status") == "local-miss"
        and isinstance(row.get("comicvine_issue_id"), int)
    ]
    attempted_rows: set[int] = set()
    matched = 0
    failed = 0
    budget_exhausted = False
    volume_batches = 0
    issue_requests = 0

    volume_groups: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in eligible:
        volume_id = row.get("comicvine_volume_id")
        if isinstance(volume_id, int):
            volume_groups[volume_id].append(row)

    for volume_id, rows in volume_groups.items():
        attempted_rows.update(id(row) for row in rows)
        try:
            roster = await client.fetch_volume_issues(volume_id, refresh=refresh)
        except ComicVineRateLimitError:
            budget_exhausted = True
            break
        except ComicVineError:
            continue

        volume_batches += 1
        roster_ids = _volume_issue_ids(roster)
        for row in rows:
            issue_id = row.get("comicvine_issue_id")
            if isinstance(issue_id, int) and issue_id in roster_ids:
                _mark_matched(
                    row,
                    provenance="comicvine-volume-roster",
                    detail=(
                        "Confirmed identity resolved through a volume-batched ComicVine issue "
                        "roster."
                    ),
                )
                matched += 1

    if not budget_exhausted:
        for row in eligible:
            if row.get("status") != "local-miss":
                continue
            issue_id = row.get("comicvine_issue_id")
            if not isinstance(issue_id, int):
                continue

            attempted_rows.add(id(row))
            issue_requests += 1
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

            provenance = "comicvine-cache" if response.from_cache else "comicvine-live"
            returned_id = _provider_issue_id(response.payload)
            if returned_id != issue_id:
                _mark_failed(
                    row,
                    provenance=provenance,
                    detail=(
                        "Provider response did not match the confirmed ComicVine issue identity."
                    ),
                )
                failed += 1
                continue

            _mark_matched(
                row,
                provenance=provenance,
                detail="Confirmed identity resolved through the budgeted ComicVine issue endpoint.",
            )
            matched += 1

    attempted = len(attempted_rows)
    _recount(report)
    report["live_refresh"] = {
        "attempted": attempted,
        "matched": matched,
        "failed": failed,
        "budget_exhausted": budget_exhausted,
        "volume_batches": volume_batches,
        "issue_requests": issue_requests,
    }
    return LiveRefreshSummary(
        attempted,
        matched,
        failed,
        budget_exhausted,
        volume_batches,
        issue_requests,
    )
