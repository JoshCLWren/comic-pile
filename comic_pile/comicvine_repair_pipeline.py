"""Local-first ComicVine identity repair pipeline with bounded live fallback."""

from __future__ import annotations

from comic_pile.comicvine_candidate_discovery import discover_local_candidates
from comic_pile.comicvine_identity_repair import (
    CandidateScore,
    ComicVineCandidate,
    ComicVineRepairContext,
    RepairDecision,
    decide_candidates,
    normalize_issue_label,
    score_candidate,
)
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError
from comic_pile.local_comicvine import LocalComicVineSnapshot


def _integer(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _publisher_name(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        name = value.get("name")
        return name.strip() if isinstance(name, str) and name.strip() else None
    return None


def _live_candidate(
    volume: dict[str, object],
    issue: dict[str, object],
    context: ComicVineRepairContext,
) -> ComicVineCandidate | None:
    volume_id = _integer(volume.get("id"))
    issue_id = _integer(issue.get("id"))
    volume_name = volume.get("name")
    if volume_id is None or issue_id is None or not isinstance(volume_name, str):
        return None
    issue_number_value = issue.get("issue_number")
    issue_name_value = issue.get("name")
    issue_number = str(issue_number_value) if issue_number_value is not None else None
    issue_name = issue_name_value if isinstance(issue_name_value, str) else None
    expected = normalize_issue_label(context.issue_label)
    if expected not in {
        normalize_issue_label(issue_number),
        normalize_issue_label(issue_name),
    }:
        return None
    return ComicVineCandidate(
        issue_id=issue_id,
        volume_id=volume_id,
        volume_name=volume_name,
        issue_number=issue_number,
        issue_name=issue_name,
        publisher=_publisher_name(volume.get("publisher")),
        start_year=_integer(volume.get("start_year")),
        source="comicvine-live",
    )


async def discover_live_candidates(
    client: ComicVineClient,
    context: ComicVineRepairContext,
    *,
    limit: int = 10,
) -> list[ComicVineCandidate]:
    """Search live ComicVine only after local evidence is insufficient.

    Provider search rank is treated only as discovery. Each candidate volume is locally validated
    against the issue roster returned by ``/issues`` before it can be scored.

    Args:
        client: Endpoint-budgeted ComicVine client.
        context: ComicPile-side issue evidence.
        limit: Maximum search result volumes to inspect.

    Returns:
        Validated live issue candidates sorted by stable provider IDs.

    Raises:
        ComicVineError: If the search payload is structurally invalid.
    """
    response = await client.request(
        "search",
        "search",
        {
            "query": context.title,
            "resources": "volume",
            "limit": max(1, min(limit, 100)),
            "field_list": "id,name,publisher,start_year",
        },
    )
    results = response.payload.get("results")
    if not isinstance(results, list):
        raise ComicVineError("ComicVine /search response did not contain a results list")

    candidates: list[ComicVineCandidate] = []
    seen: set[int] = set()
    for row in results:
        if not isinstance(row, dict):
            continue
        volume_id = _integer(row.get("id"))
        if volume_id is None:
            continue
        issues = await client.fetch_volume_issues(volume_id)
        for issue in issues:
            candidate = _live_candidate(row, issue, context)
            if candidate is None or candidate.issue_id in seen:
                continue
            seen.add(candidate.issue_id)
            candidates.append(candidate)
    return sorted(candidates, key=lambda candidate: (candidate.volume_id, candidate.issue_id))


async def repair_identity(
    *,
    snapshot: LocalComicVineSnapshot,
    client: ComicVineClient | None,
    context: ComicVineRepairContext,
    thread_issue_labels: list[str],
    existing_confirmed_issue_id: int | None = None,
    embedded_cbl_issue_id: int | None = None,
) -> tuple[RepairDecision, tuple[CandidateScore, ...]]:
    """Resolve one issue using exact evidence, local candidates, then bounded live fallback.

    Args:
        snapshot: Optional developer-local ComicVine snapshot.
        client: Live provider client; required only when local evidence is insufficient.
        context: ComicPile-side issue evidence.
        thread_issue_labels: Ordered labels for local segment discovery.
        existing_confirmed_issue_id: Existing confirmed mapping to preserve.
        embedded_cbl_issue_id: Exact CBL-embedded ComicVine issue identity.

    Returns:
        Safe resolution decision plus every scored candidate used to reach it.
    """
    local = discover_local_candidates(
        snapshot,
        context,
        thread_issue_labels=thread_issue_labels,
    )
    candidates = local
    if not candidates and client is not None:
        candidates = await discover_live_candidates(client, context)

    scores = tuple(score_candidate(context, candidate) for candidate in candidates)
    decision = decide_candidates(
        list(scores),
        existing_confirmed_issue_id=existing_confirmed_issue_id,
        embedded_cbl_issue_id=embedded_cbl_issue_id,
    )
    return decision, scores
