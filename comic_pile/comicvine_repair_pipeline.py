"""Local-first ComicVine identity repair pipeline with bounded live fallback."""

from __future__ import annotations

from typing import cast

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


def _candidate_from_rows(
    volume: dict[str, object],
    issue: dict[str, object],
    context: ComicVineRepairContext,
    *,
    source: str,
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
        source=source,
    )


def _object_result(payload: dict[str, object], resource: str) -> dict[str, object]:
    result = payload.get("results")
    if not isinstance(result, dict):
        raise ComicVineError(f"ComicVine {resource} response did not contain an object result")
    return cast(dict[str, object], result)


def _exact_local_candidate(
    snapshot: LocalComicVineSnapshot,
    issue_id: int,
    context: ComicVineRepairContext,
) -> ComicVineCandidate | None:
    issue = snapshot.get_issue(issue_id)
    if issue is None:
        return None
    volume_id = _integer(issue.data.get("volume_id"))
    if volume_id is None:
        return None
    volume = snapshot.get_volume(volume_id)
    if volume is None:
        return None
    issue_row = {**issue.data, "id": issue_id}
    volume_row = {**volume.data, "id": volume_id}
    return _candidate_from_rows(
        volume_row,
        issue_row,
        context,
        source="comicvine-local-sqlite",
    )


async def _exact_live_candidate(
    client: ComicVineClient,
    issue_id: int,
    context: ComicVineRepairContext,
) -> ComicVineCandidate | None:
    issue_response = await client.fetch_issue(issue_id)
    issue = _object_result(issue_response.payload, "issue")
    volume_ref = issue.get("volume")
    if not isinstance(volume_ref, dict):
        return None
    volume_id = _integer(volume_ref.get("id"))
    if volume_id is None:
        return None
    volume_response = await client.fetch_volume(volume_id)
    volume = _object_result(volume_response.payload, "volume")
    return _candidate_from_rows(volume, issue, context, source="comicvine-live")


async def discover_live_candidates(
    client: ComicVineClient,
    context: ComicVineRepairContext,
    *,
    limit: int = 10,
) -> list[ComicVineCandidate]:
    """Search live ComicVine only after local evidence is insufficient.

    Provider search rank is treated only as discovery. Each candidate volume is validated against
    the issue roster returned by ``/issues`` before it can be scored.

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
            candidate = _candidate_from_rows(row, issue, context, source="comicvine-live")
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
        existing_confirmed_issue_id: Existing confirmed mapping to preserve without search.
        embedded_cbl_issue_id: Exact CBL-embedded ComicVine issue identity.

    Returns:
        Safe resolution decision plus every scored candidate used to reach it.
    """
    if existing_confirmed_issue_id is not None:
        decision = decide_candidates([], existing_confirmed_issue_id=existing_confirmed_issue_id)
        return decision, ()

    if embedded_cbl_issue_id is not None:
        exact = _exact_local_candidate(snapshot, embedded_cbl_issue_id, context)
        if exact is None and client is not None:
            exact = await _exact_live_candidate(client, embedded_cbl_issue_id, context)
        if exact is not None:
            score = score_candidate(context, exact)
            decision = decide_candidates(
                [score],
                embedded_cbl_issue_id=embedded_cbl_issue_id,
            )
            return decision, (score,)

    candidates = discover_local_candidates(
        snapshot,
        context,
        thread_issue_labels=thread_issue_labels,
    )
    if not candidates and client is not None:
        candidates = await discover_live_candidates(client, context)

    scores = tuple(score_candidate(context, candidate) for candidate in candidates)
    decision = decide_candidates(list(scores))
    return decision, scores
