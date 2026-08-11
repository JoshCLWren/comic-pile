"""Optional deep ComicVine metadata hydration for existing issue reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from comic_pile.comicvine_provider import ComicVineClient, ComicVineError, ComicVineRateLimitError


@dataclass(frozen=True)
class DeepHydrationSummary:
    """Summary of a resumable deep-hydration pass."""

    attempted_issues: int
    hydrated_issues: int
    failed_issues: int
    discovered_story_arcs: int
    hydrated_story_arcs: int
    failed_story_arcs: int
    issue_budget_exhausted: bool
    story_arc_budget_exhausted: bool


def _provider_result(payload: Mapping[str, object]) -> dict[str, object] | None:
    """Return one singular provider result when the payload shape is valid."""
    result = payload.get("results")
    return result if isinstance(result, dict) else None


def _story_arc_ids(issue: Mapping[str, object]) -> set[int]:
    """Extract unique positive story-arc IDs from one deep issue payload."""
    credits = issue.get("story_arc_credits")
    if not isinstance(credits, list):
        return set()
    ids: set[int] = set()
    for credit in credits:
        if not isinstance(credit, dict):
            continue
        value = credit.get("id")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            ids.add(value)
    return ids


def _eligible_issue_rows(report: Mapping[str, object]) -> list[dict[str, object]]:
    """Return matched rows with confirmed integer ComicVine issue identities."""
    issues = report.get("issues")
    if not isinstance(issues, list):
        raise ValueError("hydration report must contain an issues list")
    return [
        row
        for row in issues
        if isinstance(row, dict)
        and row.get("status") == "matched"
        and isinstance(row.get("comicvine_issue_id"), int)
        and not isinstance(row.get("comicvine_issue_id"), bool)
    ]


async def hydrate_deep_metadata(
    report: dict[str, object],
    client: ComicVineClient,
    *,
    hydrate_story_arcs: bool = False,
    refresh: bool = False,
) -> DeepHydrationSummary:
    """Deep-hydrate matched issues and optionally deduplicated discovered story arcs.

    Core ComicPile state is never mutated. Deep payloads are attached only to the generated report,
    and an issue response is accepted only when its provider ID matches the already-confirmed
    identity. Story-arc IDs are collected into a set before any story-arc request is made so an arc
    credited by many issues consumes at most one cached/live request in a pass.

    Args:
        report: Machine-readable hydration report produced by the base hydrator.
        client: Endpoint-budgeted ComicVine provider client.
        hydrate_story_arcs: Fetch unique story arcs discovered from deep issue responses.
        refresh: Bypass successful provider cache entries when true.

    Returns:
        Counts and endpoint-budget state for the pass.
    """
    rows = _eligible_issue_rows(report)
    attempted_issues = 0
    hydrated_issues = 0
    failed_issues = 0
    issue_budget_exhausted = False
    discovered_arc_ids: set[int] = set()

    for row in rows:
        issue_id = row.get("comicvine_issue_id")
        if not isinstance(issue_id, int) or isinstance(issue_id, bool):
            continue
        attempted_issues += 1
        try:
            response = await client.fetch_issue(issue_id, refresh=refresh)
        except ComicVineRateLimitError:
            issue_budget_exhausted = True
            break
        except ComicVineError as exc:
            row["deep_hydration"] = {
                "status": "failed",
                "detail": str(exc),
            }
            failed_issues += 1
            continue

        result = _provider_result(response.payload)
        returned_id = result.get("id") if result is not None else None
        if returned_id != issue_id:
            row["deep_hydration"] = {
                "status": "failed",
                "detail": "Provider response did not match the confirmed ComicVine issue identity.",
            }
            failed_issues += 1
            continue

        row["deep_hydration"] = {
            "status": "hydrated",
            "provenance": "comicvine-cache" if response.from_cache else "comicvine-live",
            "metadata": result,
        }
        discovered_arc_ids.update(_story_arc_ids(result))
        hydrated_issues += 1

    story_arcs: dict[str, object] = {}
    hydrated_story_arcs = 0
    failed_story_arcs = 0
    story_arc_budget_exhausted = False
    if hydrate_story_arcs:
        for arc_id in sorted(discovered_arc_ids):
            try:
                response = await client.fetch_story_arc(arc_id, refresh=refresh)
            except ComicVineRateLimitError:
                story_arc_budget_exhausted = True
                break
            except ComicVineError as exc:
                story_arcs[str(arc_id)] = {"status": "failed", "detail": str(exc)}
                failed_story_arcs += 1
                continue

            result = _provider_result(response.payload)
            returned_id = result.get("id") if result is not None else None
            if returned_id != arc_id:
                story_arcs[str(arc_id)] = {
                    "status": "failed",
                    "detail": "Provider response did not match the discovered ComicVine story arc.",
                }
                failed_story_arcs += 1
                continue
            story_arcs[str(arc_id)] = {
                "status": "hydrated",
                "provenance": "comicvine-cache" if response.from_cache else "comicvine-live",
                "metadata": result,
            }
            hydrated_story_arcs += 1

    if hydrate_story_arcs:
        report["story_arcs"] = story_arcs

    summary = DeepHydrationSummary(
        attempted_issues=attempted_issues,
        hydrated_issues=hydrated_issues,
        failed_issues=failed_issues,
        discovered_story_arcs=len(discovered_arc_ids),
        hydrated_story_arcs=hydrated_story_arcs,
        failed_story_arcs=failed_story_arcs,
        issue_budget_exhausted=issue_budget_exhausted,
        story_arc_budget_exhausted=story_arc_budget_exhausted,
    )
    report["deep_hydration"] = asdict(summary)
    return summary
