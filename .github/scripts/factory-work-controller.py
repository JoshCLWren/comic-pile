#!/usr/bin/env python3
"""Deterministic assignment and lease reconciliation for ComicPile factories.

The control plane owns repository-wide prioritization. Fixed-model workers only
execute the target currently leased to their ``factory:<n>`` owner label.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

REPO = os.environ.get("GITHUB_REPOSITORY", "JoshCLWren/comic-pile")
NON_EXECUTABLE_ISSUES = {679, 1093, 1109}

OWNER_RE = re.compile(r"^factory:(?:unowned|local|[1-9]|[1-3][0-9]|4[0-6])$")
# Factories 1-5 are scheduled ChatGPT workers. The fixed-model entry workflow
# only owns 6-46, so this controller must respect 1-5 leases but never
# their liveness from fixed-model Actions runs.
FIXED_OWNER_RE = re.compile(r"^factory:(?P<worker>[6-9]|[1-3][0-9]|4[0-6])$")
STAGE_LABELS = {
    "factory:building",
    "factory:review",
    "factory:changes-requested",
    "factory:ci",
    "factory:ready",
    "factory:blocked",
}
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
LEASE_ACTIVITY_PATTERNS = (
    re.compile(r"comic-pile-factory-implement-(?:claim|progress)-v3:issue-\d+:[^:>]+:(\d{10})"),
    re.compile(r"comic-pile-factory-fix-(?:claim|progress)-v3:[^:>]+:[^:>]+:(\d{10})"),
    re.compile(r"comic-pile-factory-review-claim-v2:[^:>]+:[^:>]+:(\d{10})"),
)
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


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
GH_TIMEOUT_SECONDS = env_positive_int("FACTORY_GH_TIMEOUT_SECONDS", 120)


@dataclass(frozen=True)
class Candidate:
    kind: str
    number: int
    lane: int
    priority: int
    created_at: str
    linked_issue: int | None = None

    def sort_key(self) -> tuple[int, int, float, int]:
        # This preserves the fleet's established newest-first tie break. The
        # canonical policy explicitly requires it for equal-priority user bugs.
        return (self.lane, -self.priority, -parse_time(self.created_at), -self.number)


def parse_time(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def labels_of(item: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for label in item.get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else label
        if name:
            result.add(str(name))
    return result


def owner_of(labels: Iterable[str]) -> str | None:
    owners = [label for label in labels if OWNER_RE.fullmatch(label)]
    active = [label for label in owners if label != "factory:unowned"]
    if active:
        # Multiple active owners are an inconsistent state, but they are still
        # occupied. Returning one prevents accidental theft until reconciliation.
        return sorted(active)[0]
    return "factory:unowned" if "factory:unowned" in owners else None


def priority_rank(labels: Iterable[str]) -> int:
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
    if not branch:
        return None
    # Canonical fixed-model branches are factory/<worker>-<issue>-<suffix>.
    # Do not guess that factory/<n>-<suffix> encodes an issue because the
    # worker-side parser does not support that ambiguous shape either.
    match = re.match(r"^factory/\d+-(\d+)-", branch)
    return int(match.group(1)) if match else None


def provenance_lane(labels: set[str]) -> int:
    # Provenance beats generic bug classification. E2E-discovered bugs stay in
    # their explicit fallback lane even if another generic label is present.
    if "e2e-discovered" in labels:
        return 4
    if labels & INFRA_LABELS:
        return 5
    if "user-reported" in labels and "bug" in labels:
        return 1
    return 3


def item_is_unowned(labels: set[str]) -> bool:
    return owner_of(labels) in (None, "factory:unowned")


def issue_is_static_candidate(issue: dict[str, Any], suppressing_pr_issues: set[int]) -> bool:
    number = int(issue["number"])
    labels = labels_of(issue)
    title = str(issue.get("title") or "")
    if number in NON_EXECUTABLE_ISSUES or number in suppressing_pr_issues:
        return False
    if title.startswith(("Epic:", "PRD:")):
        return False
    if labels & BLOCKED_LABELS:
        return False
    if "ralph-status:done" in labels or "factory:ready" in labels:
        return False
    return item_is_unowned(labels)


def pr_is_static_candidate(pr: dict[str, Any], issue_map: dict[int, dict[str, Any]]) -> bool:
    if pr.get("isDraft"):
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


def pr_suppresses_issue_candidate(pr: dict[str, Any], issue_map: dict[int, dict[str, Any]]) -> bool:
    """Return whether this PR should stand in for its linked issue in the queue.

    Ready PRs are owned by the merge controller. Other PRs suppress duplicate
    issue implementation only when the PR itself is executable. Draft, blocked,
    or otherwise ineligible PRs must never make the linked issue disappear.
    """
    labels = labels_of(pr)
    if "factory:ready" in labels and not pr.get("isDraft"):
        return True
    return pr_is_static_candidate(pr, issue_map)


def build_candidates(
    issues: list[dict[str, Any]], prs: list[dict[str, Any]]
) -> list[Candidate]:
    issue_map = {int(issue["number"]): issue for issue in issues}
    suppressing_pr_issues = {
        linked
        for pr in prs
        if (linked := linked_issue_from_branch(pr.get("headRefName"))) is not None
        and pr_suppresses_issue_candidate(pr, issue_map)
    }
    candidates: list[Candidate] = []

    for is