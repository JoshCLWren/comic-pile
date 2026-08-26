#!/usr/bin/env python3
"""Select a provider candidate using trusted durable runtime evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from factory_completion_controller import (
    FAILURE_COOLDOWN_SECONDS,
    RATE_LIMIT_COOLDOWN_SECONDS,
    parse_time,
)
from factory_work_policy import comment_is_trusted


PROVIDER_RE = re.compile(r"(?m)^Source:\s*(?P<provider>\S+)\s*$")
MODEL_RE = re.compile(r"(?m)^Model:\s*(?P<model>\S+)\s*$")
OUTCOME_RE = re.compile(
    r"(?m)^Attempt outcome:\s*(?P<outcome>[a-z][a-z0-9_]+)\s*$"
)
UPDATED_RE = re.compile(r"(?m)^Updated:\s*(?P<updated>\S+)\s*$")
HEALTHY_OUTCOMES = {
    "success",
    "work_failure",
    "no_change",
    "policy_blocked",
}
IGNORED_MODEL_OUTCOMES = {
    "control_plane_failure",
    "worker_environment_failure",
}


@dataclass(frozen=True)
class AttemptEvidence:
    """Latest normalized outcome for one provider/model attempt."""

    provider: str
    model: str
    outcome: str
    updated: int


@dataclass(frozen=True)
class RankedCandidate:
    """One discovered candidate annotated with runtime health."""

    provider: str
    model: str
    runtime_model: str
    discovered_by: str
    health_state: str


@dataclass(frozen=True)
class Selection:
    """Health-ranked selection result for one dispatched slot."""

    selected: RankedCandidate | None
    candidates: tuple[RankedCandidate, ...]
    failure_outcome: str
    detail: str


def flatten_comments(payload: object) -> list[Mapping[str, Any]]:
    """Flatten one page or a slurped list of GitHub comment pages."""
    if not isinstance(payload, list):
        return []
    flattened: list[Mapping[str, Any]] = []
    for item in payload:
        if isinstance(item, Mapping):
            flattened.append(item)
        elif isinstance(item, list):
            flattened.extend(value for value in item if isinstance(value, Mapping))
    return flattened


def latest_attempt_evidence(
    comments: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], AttemptEvidence]:
    """Return the latest trusted normalized attempt per provider/model."""
    latest: dict[tuple[str, str], AttemptEvidence] = {}
    for comment in comments:
        if not comment_is_trusted(comment):
            continue
        body = str(comment.get("body") or "")
        provider_match = PROVIDER_RE.search(body)
        model_match = MODEL_RE.search(body)
        outcome_match = OUTCOME_RE.search(body)
        updated_match = UPDATED_RE.search(body)
        if (
            provider_match is None
            or model_match is None
            or outcome_match is None
            or updated_match is None
        ):
            continue
        updated = parse_time(updated_match.group("updated"))
        if updated is None:
            continue
        outcome = outcome_match.group("outcome")
        if outcome in IGNORED_MODEL_OUTCOMES:
            continue
        evidence = AttemptEvidence(
            provider=provider_match.group("provider"),
            model=model_match.group("model"),
            outcome=outcome,
            updated=updated,
        )
        key = (evidence.provider, evidence.model)
        previous = latest.get(key)
        if previous is None or evidence.updated > previous.updated:
            latest[key] = evidence
    return latest


def _provider_state(
    provider: str,
    evidence: Iterable[AttemptEvidence],
    *,
    now_epoch: int,
) -> str:
    """Return provider health from the newest provider-relevant attempt."""
    relevant = [
        item
        for item in evidence
        if item.provider == provider and item.outcome != "unknown_failure"
    ]
    if not relevant:
        return "unknown"
    newest = max(relevant, key=lambda item: item.updated)
    if newest.outcome != "provider_unavailable":
        return "healthy"
    if now_epoch < newest.updated + RATE_LIMIT_COOLDOWN_SECONDS:
        return "cooling"
    return "degraded"


def _model_state(
    provider: str,
    model: str,
    evidence: Mapping[tuple[str, str], AttemptEvidence],
    *,
    now_epoch: int,
) -> str:
    """Return model health without attributing control-plane faults to it."""
    item = evidence.get((provider, model))
    if item is None:
        return "unknown"
    if item.outcome in HEALTHY_OUTCOMES:
        return "healthy"
    if item.outcome == "model_unavailable":
        return "unavailable"
    if item.outcome in IGNORED_MODEL_OUTCOMES:
        return "unknown"
    if item.outcome in {"model_interruption", "unknown_failure"}:
        if now_epoch < item.updated + FAILURE_COOLDOWN_SECONDS:
            return "cooling"
        return "degraded"
    if item.outcome == "provider_unavailable":
        return "unknown"
    return "unknown"


def rank_candidates(
    candidates: Sequence[Mapping[str, Any]],
    comments: Iterable[Mapping[str, Any]],
    *,
    now_epoch: int,
) -> tuple[RankedCandidate, ...]:
    """Annotate discovered candidates with combined provider/model health."""
    evidence = latest_attempt_evidence(comments)
    attempts = tuple(evidence.values())
    ranked: list[RankedCandidate] = []
    for candidate in candidates:
        provider = str(candidate.get("provider") or "")
        model = str(candidate.get("model") or "")
        runtime_model = str(candidate.get("runtime_model") or "")
        discovered_by = str(candidate.get("discovered_by") or "")
        if not all((provider, model, runtime_model, discovered_by)):
            continue

        provider_state = _provider_state(provider, attempts, now_epoch=now_epoch)
        model_state = _model_state(
            provider,
            model,
            evidence,
            now_epoch=now_epoch,
        )
        if model_state == "unavailable":
            state = "unavailable"
        elif provider_state == "cooling" or model_state == "cooling":
            state = "cooling"
        elif model_state == "healthy" and provider_state in {
            "healthy",
            "degraded",
            "unknown",
        }:
            state = "healthy" if provider_state != "degraded" else "degraded"
        elif model_state == "degraded" or provider_state == "degraded":
            state = "degraded"
        else:
            state = "unknown"
        ranked.append(
            RankedCandidate(
                provider=provider,
                model=model,
                runtime_model=runtime_model,
                discovered_by=discovered_by,
                health_state=state,
            )
        )
    return tuple(ranked)


def select_candidate(
    candidates: Sequence[Mapping[str, Any]],
    comments: Iterable[Mapping[str, Any]],
    *,
    worker: int,
    now_epoch: int,
) -> Selection:
    """Prefer healthy, then degraded, then unknown probe candidates."""
    comment_list = tuple(comments)
    ranked = rank_candidates(candidates, comment_list, now_epoch=now_epoch)
    priority = {"healthy": 0, "degraded": 1, "unknown": 2}
    usable = [candidate for candidate in ranked if candidate.health_state in priority]
    if usable:
        best_priority = min(priority[candidate.health_state] for candidate in usable)
        best = sorted(
            (
                candidate
                for candidate in usable
                if priority[candidate.health_state] == best_priority
            ),
            key=lambda candidate: (candidate.model, candidate.runtime_model),
        )
        selected = best[(worker - 1) % len(best)]
        return Selection(
            selected=selected,
            candidates=ranked,
            failure_outcome="",
            detail=(
                f"selected {selected.health_state} candidate from "
                f"{len(best)} best-tier option(s)"
            ),
        )

    states = {candidate.health_state for candidate in ranked}
    evidence = latest_attempt_evidence(comment_list)
    attempts = tuple(evidence.values())
    providers = {candidate.provider for candidate in ranked}
    provider_cooling = any(
        _provider_state(provider, attempts, now_epoch=now_epoch) == "cooling"
        for provider in providers
    )
    cooling_outcomes = {
        item.outcome
        for candidate in ranked
        if candidate.health_state == "cooling"
        for item in [evidence.get((candidate.provider, candidate.model))]
        if item is not None
    }
    if provider_cooling:
        failure = "provider_unavailable"
        detail = "provider-wide evidence is cooling all discovered candidates"
    elif "unknown_failure" in cooling_outcomes:
        failure = "unknown_failure"
        detail = "unknown candidate failures are still cooling"
    elif "model_interruption" in cooling_outcomes:
        failure = "model_interruption"
        detail = "transient model interruptions are still cooling"
    elif "cooling" in states:
        failure = "unknown_failure"
        detail = "all discovered candidates are cooling without safe attribution"
    elif states == {"unavailable"}:
        failure = "model_unavailable"
        detail = "all discovered candidates have permanent unavailable evidence"
    else:
        failure = "unknown_failure"
        detail = "no discovered candidate has executable health"
    return Selection(
        selected=None,
        candidates=ranked,
        failure_outcome=failure,
        detail=detail,
    )


def main() -> int:
    """Select one candidate from discovery JSON and durable issue comments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--comments", type=Path, required=True)
    parser.add_argument("--worker", type=int, required=True)
    parser.add_argument("--now", type=int, default=None)
    args = parser.parse_args()

    discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
    comments_payload = json.loads(args.comments.read_text(encoding="utf-8"))
    candidates = discovery.get("candidates") if isinstance(discovery, Mapping) else None
    if not isinstance(candidates, list):
        candidates = []
    selection = select_candidate(
        candidates,
        flatten_comments(comments_payload),
        worker=args.worker,
        now_epoch=args.now if args.now is not None else int(time.time()),
    )
    print(json.dumps(asdict(selection), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
