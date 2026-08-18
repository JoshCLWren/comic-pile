"""Pure ranking and lease policy for the factory work controller."""
from __future__ import annotations
import os
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from factory_review_policy import producer_worker_from_pr as producer_worker_from_values
NON_EXECUTABLE_ISSUES = {679, 1093, 1109}

OWNER_RE = re.compile('^factory:(?:unowned|local|[1-9]|[1-3][0-9]|4[0-6])$')

FIXED_OWNER_RE = re.compile('^factory:(?P<worker>[6-9]|[1-3][0-9]|4[0-6])$')

STAGE_LABELS = {'factory:building', 'factory:review', 'factory:changes-requested', 'factory:ci', 'factory:ready', 'factory:blocked'}
STAGE_PRECEDENCE = ('factory:blocked', 'factory:ready', 'factory:review', 'factory:changes-requested', 'factory:ci', 'factory:building')

INFRA_LABELS = {'infrastructure', 'e2e-infrastructure', 'policy-change', 'docs', 'documentation', 'quality-control'}

# factory:blocked is reserved for a genuine terminal blocker. Model no-diff
# failures use a separate bounded retry counter supplied by the controller.
BLOCKED_LABELS = {'factory:blocked', 'ralph-status:blocked', 'wontfix', 'invalid', 'duplicate'}


def env_positive_int(name: str, default: int) -> int:
    """Return a positive integer environment setting or its safe default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f'[factory-controller] ignoring non-numeric {name}={raw!r}; using {default}', file=sys.stderr)
        return default
    if value <= 0:
        print(f'[factory-controller] ignoring non-positive {name}={raw!r}; using {default}', file=sys.stderr)
        return default
    return value


LOCAL_LEASE_TTL_SECONDS = env_positive_int('FACTORY_LOCAL_LEASE_TTL_SECONDS', 3600)
FACTORY_PR_WIP_LIMIT = env_positive_int('FACTORY_PR_WIP_LIMIT', 5)
FACTORY_NO_DIFF_RETRY_LIMIT = env_positive_int('FACTORY_NO_DIFF_RETRY_LIMIT', 3)


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
    conflicted: bool = False

    def sort_key(self) -> tuple[int, int, float, int]:
        """Return the deterministic queue ordering key."""
        return (self.lane, -self.priority, -parse_time(self.created_at), -self.number)


def parse_time(value: str | None) -> float:
    """Parse an ISO timestamp into a sortable epoch value."""
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return 0.0


def labels_of(item: dict[str, Any]) -> set[str]:
    """Return the normalized label names from a GitHub item."""
    result: set[str] = set()
    for label in item.get('labels') or []:
        name = label.get('name') if isinstance(label, dict) else label
        if name:
            result.add(str(name))
    return result


def owner_of(labels: Iterable[str]) -> str | None:
    """Return the active factory owner represented by a label set."""
    owners = [label for label in labels if OWNER_RE.fullmatch(label)]
    active = [label for label in owners if label != 'factory:unowned']
    if active:
        return sorted(active)[0]
    return 'factory:unowned' if 'factory:unowned' in owners else None


def priority_rank(labels: Iterable[str]) -> int:
    """Map explicit priority labels to a deterministic numeric rank."""
    labels = set(labels)
    if 'ralph-priority:critical' in labels or 'priority:P0' in labels:
        return 4
    if 'ralph-priority:high' in labels or 'priority: high' in labels:
        return 3
    if 'ralph-priority:medium' in labels:
        return 2
    if 'ralph-priority:low' in labels:
        return 1
    return 0


def linked_issue_from_branch(branch: str | None) -> int | None:
    """Extract an issue number from the canonical factory branch shape."""
    if not branch:
        return None
    match = re.match('^factory/\\d+-(\\d+)-', branch)
    return int(match.group(1)) if match else None


def producer_worker_from_pr(pr: dict[str, Any]) -> str | None:
    """Recover producer identity using the shared review provenance policy."""
    return producer_worker_from_values(branch=str(pr.get('headRefName') or ''), body=str(pr.get('body') or ''))


def stage_of(labels: Iterable[str]) -> str | None:
    """Return the deterministic current factory lifecycle stage."""
    present = set(labels)
    return next((label for label in STAGE_PRECEDENCE if label in present), None)


def provenance_lane(labels: set[str]) -> int:
    """Return the deterministic assignment lane for a label set."""
    if 'e2e-discovered' in labels:
        return 4
    if labels & INFRA_LABELS:
        return 5
    if 'user-reported' in labels and 'bug' in labels:
        return 1
    return 3


def item_is_unowned(labels: set[str]) -> bool:
    """Return whether a label set has no active factory owner."""
    return owner_of(labels) in (None, 'factory:unowned')


def issue_bypasses_wip_limit(issue: dict[str, Any]) -> bool:
    """Keep genuinely urgent product defects executable while PR work is saturated."""
    labels = labels_of(issue)
    return (
        ('user-reported' in labels and 'bug' in labels)
        or 'priority:P0' in labels
        or 'ralph-priority:critical' in labels
    )


def factory_pr_wip_count(prs: Iterable[dict[str, Any]]) -> int:
    """Count factory PRs that currently consume a worker lease.

    Queue depth is not worker WIP. Unowned PRs waiting for a reviewer and PRs in
    factory:ready waiting for the merge drain consume no fixed-model worker
    capacity, so they must not shut off issue intake merely by existing.
    """
    count = 0
    for pr in prs:
        if str(pr.get('state') or 'OPEN').upper() != 'OPEN' or pr.get('isDraft'):
            continue
        labels = labels_of(pr)
        head = str(pr.get('headRefName') or '')
        if not head.startswith('factory/'):
            continue
        if 'factory:ready' in labels or labels & BLOCKED_LABELS:
            continue
        owner = owner_of(labels)
        if owner not in (None, 'factory:unowned'):
            count += 1
    return count


def pr_is_conflicted(pr: dict[str, Any]) -> bool:
    """Return whether GitHub reports the current PR head as merge-conflicted."""
    mergeable = str(pr.get('mergeable') or '').upper()
    merge_state = str(pr.get('mergeStateStatus') or '').upper()
    return mergeable == 'CONFLICTING' or merge_state == 'DIRTY'


def issue_is_static_candidate(
    issue: dict[str, Any],
    suppressing_pr_issues: set[int],
    *,
    no_diff_attempts: int = 0,
) -> bool:
    """Return whether an issue is structurally eligible for assignment."""
    number = int(issue['number'])
    labels = labels_of(issue)
    title = str(issue.get('title') or '')
    if str(issue.get('state') or 'OPEN').upper() != 'OPEN':
        return False
    if number in NON_EXECUTABLE_ISSUES or number in suppressing_pr_issues:
        return False
    if title.startswith(('Epic:', 'PRD:')):
        return False
    if labels & BLOCKED_LABELS:
        return False
    if no_diff_attempts >= FACTORY_NO_DIFF_RETRY_LIMIT:
        return False
    if 'ralph-status:done' in labels or 'factory:ready' in labels:
        return False
    return item_is_unowned(labels)


def pr_is_static_candidate(pr: dict[str, Any], issue_map: dict[int, dict[str, Any]]) -> bool:
    """Return whether an open autonomous-factory PR is structurally eligible."""
    if str(pr.get('state') or 'OPEN').upper() != 'OPEN' or pr.get('isDraft'):
        return False
    labels = labels_of(pr)
    head = str(pr.get('headRefName') or '')
    # Human-authored agent/* and chatgpt/* PRs are not autonomous factory work,
    # even if a stale/mistaken factory label was applied to them.
    if not head.startswith('factory/'):
        return False
    if labels & BLOCKED_LABELS or 'factory:ready' in labels:
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
    """Return whether this open factory PR is canonical work for its issue.

    Once a canonical factory PR exists, the linked issue must not become fresh
    implementation work again just because the PR is currently owned, blocked,
    under review, or otherwise not assignable. The PR lifecycle is the only
    path forward until that PR closes.
    """
    del issue_map  # Kept in the signature for compatibility with existing callers.
    head = str(pr.get('headRefName') or '')
    return str(pr.get('state') or 'OPEN').upper() == 'OPEN' and head.startswith('factory/')


def build_candidates(
    issues: list[dict[str, Any]],
    prs: list[dict[str, Any]],
    *,
    no_diff_attempts_by_issue: Mapping[int, int] | None = None,
) -> list[Candidate]:
    """Build and rank executable issue and pull-request candidates."""
    issue_map = {int(issue['number']): issue for issue in issues}
    retry_counts = no_diff_attempts_by_issue or {}
    suppressing_pr_issues = {
        linked
        for pr in prs
        if (linked := linked_issue_from_branch(pr.get('headRefName'))) is not None
        and pr_suppresses_issue_candidate(pr, issue_map)
    }
    pr_wip_full = factory_pr_wip_count(prs) >= FACTORY_PR_WIP_LIMIT
    candidates: list[Candidate] = []
    for issue in issues:
        number = int(issue['number'])
        if not issue_is_static_candidate(
            issue,
            suppressing_pr_issues,
            no_diff_attempts=max(0, int(retry_counts.get(number, 0))),
        ):
            continue
        if pr_wip_full and not issue_bypasses_wip_limit(issue):
            continue
        labels = labels_of(issue)
        candidates.append(
            Candidate(
                kind='issue',
                number=number,
                lane=provenance_lane(labels),
                priority=priority_rank(labels),
                created_at=str(issue.get('createdAt') or ''),
                stage=stage_of(labels),
            )
        )
    for pr in prs:
        if not pr_is_static_candidate(pr, issue_map):
            continue
        linked = linked_issue_from_branch(pr.get('headRefName'))
        pr_labels = labels_of(pr)
        labels = set(pr_labels)
        if linked is not None and linked in issue_map:
            labels |= labels_of(issue_map[linked])
        lane = provenance_lane(labels)
        if lane == 1:
            lane = 2
        candidates.append(
            Candidate(
                kind='pr',
                number=int(pr['number']),
                lane=lane,
                priority=priority_rank(labels),
                created_at=str(pr.get('createdAt') or ''),
                linked_issue=linked,
                stage=stage_of(pr_labels),
                producer_worker=producer_worker_from_pr(pr),
                conflicted=pr_is_conflicted(pr),
            )
        )
    return sorted(candidates, key=Candidate.sort_key)


def review_capacity_worker(worker: str) -> bool:
    """Return whether this deterministic worker slot prioritizes review intake."""
    return int(worker) % 4 == 2


def candidate_is_independent_for_worker(candidate: Candidate, worker: str) -> bool:
    """Prevent a producing factory from being assigned semantic review of its PR."""
    return not (
        candidate.kind == 'pr'
        and candidate.stage == 'factory:review'
        and candidate.producer_worker == worker
    )


def order_candidates_for_worker(candidates: list[Candidate], worker: str) -> list[Candidate]:
    """Balance completion pressure with a deterministic fresh-issue intake lane."""
    eligible = [
        candidate
        for candidate in candidates
        if candidate_is_independent_for_worker(candidate, worker)
    ]
    review_first = review_capacity_worker(worker)

    def work_class(candidate: Candidate) -> int:
        if candidate.kind == 'pr':
            if candidate.conflicted:
                return 0
            if candidate.stage == 'factory:ci':
                return 1
            if candidate.stage == 'factory:changes-requested':
                return 2
            if candidate.stage == 'factory:review':
                return 3 if review_first else 6
            return 4 if review_first else 7
        if candidate.lane == 1:
            return 5 if review_first else 3
        return 6 if review_first else 4

    return sorted(
        eligible,
        key=lambda candidate: (work_class(candidate), candidate.sort_key()),
    )


def plan_distinct_assignments(candidates: list[Candidate], workers: list[str]) -> dict[str, Candidate]:
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


def lease_is_stale(owner: str, *, active_fixed_workers: set[int], latest_activity_epoch: int | None, now_epoch: int, local_ttl_seconds: int=LOCAL_LEASE_TTL_SECONDS) -> bool:
    """Return whether a factory lease can be proven stale."""
    if owner == 'factory:local':
        return latest_activity_epoch is not None and now_epoch - latest_activity_epoch > local_ttl_seconds
    match = FIXED_OWNER_RE.fullmatch(owner)
    if match:
        return int(match.group('worker')) not in active_fixed_workers
    return False
