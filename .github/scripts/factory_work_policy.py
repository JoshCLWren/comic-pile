"""Pure ranking and lease policy for the factory work controller."""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from factory_review_policy import (
    producer_worker_from_pr as producer_worker_from_values,
)

NON_EXECUTABLE_ISSUES = {679, 1093, 1109}

OWNER_RE = re.compile(r"^factory:(?:unowned|local|[1-9]|[1-3][0-9]|4[0-6])$")
FIXED_OWNER_RE = re.compile(r"^factory:(?P<worker>[6-9]|[1-3][0-9]|4[0-6])$")

STAGE_LABELS = {
    "factory:building",
    "factory:review",
    "factory:changes-requested",
    "factory:ci",
    "factory:ready",
    "factory:blocked",
}
STAGE_PRECEDENCE = (
    "factory:blocked",
    "factory:ready",
    "factory:review",
    "factory:changes-requested",
    "factory:ci",
    "factory:building",
)
INFRA_LABELS = {
    "infrastructure",
    "e2e-infrastructure",
    "policy-change",
    "docs",
    "documentation",
    "quality-control",
}
BLOCKED_LABELS = {
    "factory:blocked",
    "ralph-status:blocked",
    "wontfix",
    "invalid",
    "duplicate",
}


def env_positive_int(name: str, default: int) -> int:
    """Return a positive integer environment setting or its safe default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(
            f"[factory-controller] ignoring non-numeric {name}={raw!r}; using {default}",
            file=sys.stderr,
        )
        return default
    if value <= 0:
        print(
            f"[factory-controller] ignoring non-positive {name}={raw!r}; using {default}",
            file=sys.stderr,
        )
        return default
    return value


LOCAL_LEASE_TTL_SECONDS = env_positive_int("FACTORY_LOCAL_LEASE_TTL_SECONDS", 3600)


@dataclass(frozen=True)
class Candidate:
    """A ranked unit of executable factory work."""

    kind: str
    number: int
    lane: int
    priority: int
    created_at: str
    linked_issue: int | None = None
    stage: str | None = None
    producer_worker: str | None = None

    def sort_key(self) -> tuple[int, int, float, int]:
        """Return the deterministic queue ordering key."""
        return (self.lane, -self.priority, -parse_time(self.created_at), -self.number)


def parse_time(value: str | None) -> float:
    """Parse an ISO timestamp into a sortable epoch value."""
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def labels_of(item: dict[str, Any]) -> set[str]:
    """Return the normalized label names from a GitHub item."""
    result: set[str] = set()
    for label in item.get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else label
        if name:
            result.add(str(name))
    return result


def owner_of(labels: Iterable[str]) -> str | None:
    """Return the active factory owner represented by a label set."""
    owners = [label for label in labels if OWNER_RE.fullmatch(label)]
    active = [label for label in owners if label != "factory:unowned"]
    if active:
        return sorted(active)[0]
    return "factory:unowned" if "factory:unowned" in owners else None


def priority_rank(labels: Iterable[str]) -> int:
    """Map explicit priority labels to a deterministic numeric rank."""
    labels = set(labels)
    if "ralph-priority:critical" in labels or "priority:P0" in labels:
        return 4
    if "ralph-priority:high" in labels or "priority: high" in labels:
        return 3
    if "ralph-priority:medium" in labels:
        return 2
    if "ralph-priority:low" in labels:
        return 1
    return 0


def linked_issue_from_branch(branch: str | None) -> int | None:
    """Extract an issue number from the canonical factory branch shape."""
    if not branch:
        return None
    match = re.match(r"^factory/\d+-(\d+)-", branch)
    return int(match.group(1)) if match else None


def producer_worker_from_pr(pr: dict[str, Any]) -> str | None:
    """Recover producer identity using the shared review provenance policy."""
    return producer_worker_from_values(
        branch=str(pr.get("headRefName") or ""),
        body=str(pr.get("body") or ""),
    )


def stage_of(labels: Iterable[str]) -> str | None:
    """Return the deterministic current factory lifecycle stage."""
    present = set(labels)
    return next((label for label in STAGE_PRECEDENCE if label in present), None)


def provenance_lane(labels: set[str]) -> int:
    """Return the deterministic assignment lane for a label set."""
    if "e2e-discovered" in labels:
        return 4
    if labels & INFRA_LABELS:
        return 5
    if "user-reported" in labels and "bug" in labels:
        return 1
    return 3


def item_is_unowned(labels: set[str]) -> bool:
    """Return whether a label set has no active factory owner."""
    return owner_of(labels) in (None, "factory:unowned")


def issue_is_static_candidate(
    issue: dict[str, Any],
    suppressing_pr_issues: set[int],
) -> bool:
    """Return whether an issue is structurally eligible for assignment."""
    number = int(issue["number"])
    labels = labels_of(issue)
    title = str(issue.get("title") or "")
    state = str(issue.get("state") or "OPEN").upper()
    if state != "OPEN":
        return False
    if number in NON_EXECUTABLE_ISSUES or number in suppressing_pr_issues:
        return False
    if title.startswith(("Epic:", "PRD:")):
        return False
    if labels & BLOCKED_LABELS:
        return False
    if "ralph-status:done" in labels or "factory:ready" in labels:
        return False
    return item_is_unowned(labels)


def pr_is_static_candidate(
    pr: dict[str, Any],
    issue_map: dict[int, dict[str, Any]],
) -> bool:
    """Return whether an open factory PR is structurally eligible for work."""
    state = str(pr.get("state") or "OPEN").upper()
    if state != "OPEN" or pr.get("isDraft"):
        return False
    labels = labels_of(pr)
    head = str(pr.get("headRefName") or "")
    if "factory" not in labels and not head.startswith("factory/"):
        return False
    if labels & BLOCKED_LABELS or "factory:ready" in labels:
        return False
    if not item_is_unowned(labels):
        return False
    linked = linked_issue_from_branch(head)
    if linked is not None and linked in issue_map:
        issue_labels = labels_of(issue_map[linked])
        if not item_is_unowned(issue_labels) or issue_labels & BLOCKED_LABELS:
            return False
    return True


def pr_suppresses_issue_candidate(
    pr: dict[str, Any],
    issue_map: dict[int, dict[str, Any]],
) -> bool:
    """Return whether this PR should stand in for its linked issue in the queue.

    Ready PRs are owned by the merge controller. Other PRs suppress duplicate
    issue implementation only when the PR itself is executable. Draft, blocked,
    closed, or otherwise ineligible PRs must never make the linked issue
    disappear.
    """
    state = str(pr.get("state") or "OPEN").upper()
    if state != "OPEN":
        return False
    labels = labels_of(pr)
    if "factory:ready" in labels and not pr.get("isDraft"):
        return True
    return pr_is_static_candidate(pr, issue_map)


def build_candidates(
    issues: list[dict[str, Any]],
    prs: list[dict[str, Any]],
) -> list[Candidate]:
    """Build and rank executable issue and pull-request candidates."""
    issue_map = {int(issue["number"]): issue for issue in issues}
    suppressing_pr_issues = {
        linked
        for pr in prs
        if (linked := linked_issue_from_branch(pr.get("headRefName"))) is not None
        and pr_suppresses_issue_candidate(pr, issue_map)
    }
    candidates: list[Candidate] = []
    for issue in issues:
        if not issue_is_static_candidate(issue, suppressing_pr_issues):
            continue
        labels = labels_of(issue)
        candidates.append(
            Candidate(
                kind="issue",
                number=int(issue["number"]),
                lane=provenance_lane(labels),
                priority=priority_rank(labels),
                created_at=str(issue.get("createdAt") or ""),
                stage=stage_of(labels),
            )
        )
    for pr in prs:
        if not pr_is_static_candidate(pr, issue_map):
            continue
        linked = linked_issue_from_branch(pr.get("headRefName"))
        pr_labels = labels_of(pr)
        labels = set(pr_labels)
        if linked is not None and linked in issue_map:
            labels |= labels_of(issue_map[linked])
        lane = provenance_lane(labels)
        if lane == 1:
            lane = 2
        candidates.append(
            Candidate(
                kind="pr",
                number=int(pr["number"]),
                lane=lane,
                priority=priority_rank(labels),
                created_at=str(pr.get("createdAt") or ""),
                linked_issue=linked,
                stage=stage_of(pr_labels),
                producer_worker=producer_worker_from_pr(pr),
            )
        )
    return sorted(candidates, key=Candidate.sort_key)


def review_capacity_worker(worker: str) -> bool:
    """Reserve a stable minority of fixed workers for review-first assignment."""
    return int(worker) % 4 == 2


def candidate_is_independent_for_worker(candidate: Candidate, worker: str) -> bool:
    """Prevent a producing factory from being assigned semantic review of its PR."""
    return not (
        candidate.kind == "pr"
        and candidate.stage == "factory:review"
        and candidate.producer_worker == worker
    )


def order_candidates_for_worker(
    candidates: list[Candidate],
    worker: str,
) -> list[Candidate]:
    """Give review bounded capacity while preserving concurrent product work."""
    eligible = [
        candidate
        for candidate in candidates
        if candidate_is_independent_for_worker(candidate, worker)
    ]

    def work_class(candidate: Candidate) -> int:
        is_semantic_review = (
            candidate.kind == "pr" and candidate.stage == "factory:review"
        )
        if review_capacity_worker(worker):
            if is_semantic_review:
                return 0
            if candidate.kind == "pr":
                return 1
            return 2
        if candidate.kind == "issue":
            return 0
        if candidate.kind == "pr" and candidate.stage != "factory:review":
            return 1
        return 2

    return sorted(eligible, key=lambda candidate: (work_class(candidate), candidate.sort_key()))


def plan_distinct_assignments(
    candidates: list[Candidate],
    workers: list[str],
) -> dict[str, Candidate]:
    """Pure helper used by regression coverage for one dispatcher batch."""
    remaining = list(candidates)
    assignments: dict[str, Candidate] = {}
    for worker in workers:
        ordered = order_candidates_for_worker(remaining, worker)
        if not ordered:
            continue
        selected = ordered[0]
        assignments[worker] = selected
        remaining.remove(selected)
    return assignments


def lease_is_stale(
    owner: str,
    *,
    active_fixed_workers: set[int],
    latest_activity_epoch: int | None,
    now_epoch: int,
    local_ttl_seconds: int = LOCAL_LEASE_TTL_SECONDS,
) -> bool:
    """Return whether a factory lease can be proven stale."""
    if owner == "factory:local":
        return (
            latest_activity_epoch is not None
            and now_epoch - latest_activity_epoch > local_ttl_seconds
        )
    match = FIXED_OWNER_RE.fullmatch(owner)
    if match:
        return int(match.group("worker")) not in active_fixed_workers
    return False
