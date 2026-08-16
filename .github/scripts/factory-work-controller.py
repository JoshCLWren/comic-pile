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
LOCAL_LEASE_TTL_SECONDS = int(os.environ.get("FACTORY_LOCAL_LEASE_TTL_SECONDS", "3600"))
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


@dataclass(frozen=True)
class Candidate:
    kind: str
    number: int
    lane: int
    priority: int
    created_at: str
    linked_issue: int | None = None

    def sort_key(self) -> tuple[int, int, float, int]:
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
    match = re.match(r"^factory/\d+-(\d+)-", branch)
    if not match:
        match = re.match(r"^factory/(\d+)(?:-|$)", branch)
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
            )
        )

    for pr in prs:
        if not pr_is_static_candidate(pr, issue_map):
            continue
        linked = linked_issue_from_branch(pr.get("headRefName"))
        labels = set(labels_of(pr))
        if linked is not None and linked in issue_map:
            labels |= labels_of(issue_map[linked])
        lane = provenance_lane(labels)
        if lane == 1:
            # Existing repair/finish work directly landing a user-reported bug
            # sits immediately after fresh user-reported bug implementation.
            lane = 2
        candidates.append(
            Candidate(
                kind="pr",
                number=int(pr["number"]),
                lane=lane,
                priority=priority_rank(labels),
                created_at=str(pr.get("createdAt") or ""),
                linked_issue=linked,
            )
        )

    return sorted(candidates, key=Candidate.sort_key)


def plan_distinct_assignments(
    candidates: list[Candidate], workers: list[str]
) -> dict[str, Candidate]:
    """Pure helper used by regression coverage for one dispatcher batch."""
    return {worker: candidate for worker, candidate in zip(workers, candidates)}


def lease_is_stale(
    owner: str,
    *,
    active_fixed_workers: set[int],
    latest_activity_epoch: int | None,
    now_epoch: int,
    local_ttl_seconds: int = LOCAL_LEASE_TTL_SECONDS,
) -> bool:
    if owner == "factory:local":
        # Never reap local merely from label age. Require a trusted lease marker
        # so the controller has positive evidence that the local lease existed
        # and then stopped receiving progress.
        return (
            latest_activity_epoch is not None
            and now_epoch - latest_activity_epoch > local_ttl_seconds
        )
    match = FIXED_OWNER_RE.fullmatch(owner)
    if match:
        return int(match.group("worker")) not in active_fixed_workers
    return False


def run_gh(args: list[str], *, input_json: Any | None = None, check: bool = True) -> str:
    command = ["gh", *args]
    proc = subprocess.run(
        command,
        input=None if input_json is None else json.dumps(input_json),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode:
        raise RuntimeError(
            f"{' '.join(command)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def gh_json(args: list[str], *, input_json: Any | None = None) -> Any:
    output = run_gh(args, input_json=input_json)
    return json.loads(output) if output.strip() else None


def list_issues() -> list[dict[str, Any]]:
    return gh_json(
        [
            "issue",
            "list",
            "--repo",
            REPO,
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            "number,title,labels,createdAt,updatedAt",
        ]
    )


def list_prs() -> list[dict[str, Any]]:
    return gh_json(
        [
            "pr",
            "list",
            "--repo",
            REPO,
            "--state",
            "open",
            "--limit",
            "500",
            "--json",
            "number,title,labels,headRefName,createdAt,updatedAt,isDraft",
        ]
    )


def target_json(number: int) -> dict[str, Any]:
    return gh_json(["api", f"repos/{REPO}/issues/{number}"])


def replace_factory_labels(number: int, owner: str, stage: str | None = None) -> None:
    target = target_json(number)
    current = [label["name"] for label in target.get("labels", [])]
    existing_stage = next((label for label in current if label in STAGE_LABELS), None)
    stage = stage or existing_stage or "factory:building"
    labels = [
        label
        for label in current
        if not OWNER_RE.fullmatch(label)
        and label not in STAGE_LABELS
        and label != "factory"
    ]
    labels.extend(["factory", owner, stage])
    run_gh(
        ["api", "--method", "PUT", f"repos/{REPO}/issues/{number}/labels", "--input", "-"],
        input_json={"labels": sorted(set(labels))},
    )


def issue_has_open_blocker(number: int) -> bool:
    try:
        blockers = gh_json(
            ["api", f"repos/{REPO}/issues/{number}/dependencies/blocked_by?per_page=100"]
        )
    except RuntimeError:
        # Dependency uncertainty must not cause the controller to claim work it
        # cannot prove executable.
        return True
    return any(item.get("state") == "open" for item in blockers or [])


def required_checks_failed(pr_number: int) -> bool:
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "checks",
            str(pr_number),
            "--repo",
            REPO,
            "--required",
            "--json",
            "state",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if not proc.stdout.strip():
        return False
    try:
        checks = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False
    failure_states = {
        "FAILURE",
        "ERROR",
        "CANCELLED",
        "TIMED_OUT",
        "ACTION_REQUIRED",
        "STARTUP_FAILURE",
    }
    return any(str(check.get("state", "")).upper() in failure_states for check in checks)


def candidate_is_live_executable(candidate: Candidate) -> bool:
    if candidate.kind == "issue":
        return not issue_has_open_blocker(candidate.number)
    target = target_json(candidate.number)
    labels = {label["name"] for label in target.get("labels", [])}
    if "factory:ci" in labels:
        return required_checks_failed(candidate.number)
    # Review/changes-requested/building/unclassified PR work is executable: the
    # worker can inspect the exact head and either repair it or prove it ready.
    return True


def target_still_unowned(number: int) -> bool:
    labels = {label["name"] for label in target_json(number).get("labels", [])}
    return item_is_unowned(labels) and not bool(labels & BLOCKED_LABELS)


def assign_candidate(candidate: Candidate, worker: str) -> bool:
    owner = f"factory:{worker}"
    numbers = [candidate.number]
    if candidate.kind == "pr" and candidate.linked_issue is not None:
        try:
            issue = target_json(candidate.linked_issue)
        except RuntimeError:
            issue = None
        if issue and issue.get("state") == "open":
            numbers.insert(0, candidate.linked_issue)

    # Dispatcher serialization protects fixed-vs-fixed selection. This final
    # read also protects against a local/interactive takeover between ranking
    # and mutation.
    for number in numbers:
        if not target_still_unowned(number):
            return False

    claimed: list[int] = []
    try:
        for number in numbers:
            replace_factory_labels(number, owner, "factory:building")
            claimed.append(number)
    except Exception:
        for number in claimed:
            try:
                replace_factory_labels(number, "factory:unowned")
            except Exception:
                pass
        raise
    return True


def flatten_pages(pages: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in pages or []:
        if isinstance(page, list):
            result.extend(item for item in page if isinstance(item, dict))
        elif isinstance(page, dict):
            result.append(page)
    return result


def latest_lease_activity_epoch(number: int) -> int | None:
    try:
        pages = gh_json(
            ["api", "--paginate", "--slurp", f"repos/{REPO}/issues/{number}/comments?per_page=100"]
        )
    except RuntimeError:
        return None
    latest: int | None = None
    for comment in flatten_pages(pages):
        if comment.get("author_association") not in TRUSTED_ASSOCIATIONS:
            continue
        body = str(comment.get("body") or "")
        for pattern in LEASE_ACTIVITY_PATTERNS:
            for match in pattern.findall(body):
                epoch = int(match)
                latest = epoch if latest is None else max(latest, epoch)
    return latest


def active_fixed_workers() -> set[int]:
    workers: set[int] = set()
    runs: list[dict[str, Any]] = []
    for status in ("queued", "in_progress"):
        response = gh_json(
            [
                "api",
                f"repos/{REPO}/actions/workflows/free-model-factory-entry.yml/runs?status={status}&per_page=100",
            ]
        )
        runs.extend((response or {}).get("workflow_runs", []))

    # New entry runs encode the worker in run-name, so even queued runs are
    # authoritative before their heartbeat step executes.
    unresolved_run_ids: set[str] = set()
    for run in runs:
        title = str(run.get("display_title") or run.get("name") or "")
        match = re.search(r"\bFactory\s+(\d+)\b", title)
        if match:
            workers.add(int(match.group(1)))
        else:
            run_id = str(run.get("id") or "")
            if run_id:
                unresolved_run_ids.add(run_id)

    if unresolved_run_ids:
        pages = gh_json(
            ["api", "--paginate", "--slurp", f"repos/{REPO}/issues/1093/comments?per_page=100"]
        )
        for comment in flatten_pages(pages):
            if comment.get("author_association") not in TRUSTED_ASSOCIATIONS:
                continue
            body = str(comment.get("body") or "")
            run_match = re.search(r"(?m)^Run:\s*(\d+)\s*$", body)
            worker_match = re.search(
                r"(?m)^Worker:\s*opencode-free-model-factory-(\d+)\s*$", body
            )
            if run_match and worker_match and run_match.group(1) in unresolved_run_ids:
                workers.add(int(worker_match.group(1)))
    return workers


def owned_targets(
    issues: list[dict[str, Any]] | None = None,
    prs: list[dict[str, Any]] | None = None,
) -> list[tuple[int, str]]:
    targets: list[tuple[int, str]] = []
    issue_items = list_issues() if issues is None else issues
    pr_items = list_prs() if prs is None else prs
    for item in [*issue_items, *pr_items]:
        owner = owner_of(labels_of(item))
        if owner and owner != "factory:unowned":
            targets.append((int(item["number"]), owner))
    return targets


def reconcile_stale_leases(now_epoch: int | None = None) -> list[int]:
    now_epoch = int(time.time()) if now_epoch is None else now_epoch
    active = active_fixed_workers()
    released: list[int] = []
    for number, owner in owned_targets():
        activity = latest_lease_activity_epoch(number) if owner == "factory:local" else None
        if not lease_is_stale(
            owner,
            active_fixed_workers=active,
            latest_activity_epoch=activity,
            now_epoch=now_epoch,
        ):
            continue
        replace_factory_labels(number, "factory:unowned")
        released.append(number)
        print(
            f"[factory-controller] released stale {owner} lease on #{number}",
            file=sys.stderr,
        )
    return released


def worker_has_active_lease(worker: str) -> bool:
    owner = f"factory:{worker}"
    return any(current_owner == owner for _, current_owner in owned_targets())


def assign(worker: str) -> Candidate | None:
    if not re.fullmatch(r"(?:[6-9]|[1-3][0-9]|4[0-6])", worker):
        raise SystemExit(f"unsupported fixed-model worker: {worker}")

    # A worker with a live lease is already busy. Do not queue a second target
    # behind it and do not revive affinity to the existing target.
    if worker_has_active_lease(worker):
        print(
            f"[factory-controller] Factory {worker} already has an active lease; skipping dispatch",
            file=sys.stderr,
        )
        return None

    candidates = build_candidates(list_issues(), list_prs())
    for candidate in candidates:
        if not candidate_is_live_executable(candidate):
            continue
        if assign_candidate(candidate, worker):
            print(
                f"[factory-controller] assigned {candidate.kind} #{candidate.number} "
                f"lane={candidate.lane} priority={candidate.priority} to Factory {worker}",
                file=sys.stderr,
            )
            return candidate
    return None


def release_worker(worker: str) -> list[int]:
    owner = f"factory:{worker}"
    released: list[int] = []
    for number, current_owner in owned_targets():
        if current_owner != owner:
            continue
        replace_factory_labels(number, "factory:unowned")
        released.append(number)
    return released


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("reconcile")

    assign_parser = subparsers.add_parser("assign")
    assign_parser.add_argument("--worker", required=True)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--worker", required=True)

    args = parser.parse_args()

    if args.command == "reconcile":
        print(json.dumps({"released": reconcile_stale_leases()}))
        return 0

    if args.command == "assign":
        candidate = assign(args.worker)
        if candidate is None:
            print(json.dumps({"kind": "none"}))
            return 0
        print(
            json.dumps(
                {
                    "kind": candidate.kind,
                    "number": candidate.number,
                    "lane": candidate.lane,
                    "priority": candidate.priority,
                    "linked_issue": candidate.linked_issue,
                }
            )
        )
        return 0

    print(json.dumps({"released": release_worker(args.worker)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
