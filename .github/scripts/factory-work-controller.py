#!/usr/bin/env python3
"""Deterministic GitHub assignment and lease reconciliation for ComicPile."""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, cast
sys.path.insert(0, os.path.dirname(__file__))
from factory_work_policy import (BLOCKED_LABELS, OWNER_RE, STAGE_LABELS, Candidate, build_candidates, env_positive_int, item_is_unowned, labels_of, lease_is_stale, linked_issue_from_branch, order_candidates_for_worker, owner_of, plan_distinct_assignments)
REPO = os.environ.get("GITHUB_REPOSITORY", "JoshCLWren/comic-pile")
GH_TIMEOUT_SECONDS = env_positive_int("FACTORY_GH_TIMEOUT_SECONDS", 120)
LEASE_ACTIVITY_PATTERNS = (
    re.compile(r"comic-pile-factory-implement-(?:claim|progress)-v3:issue-\d+:[^:>]+:(\d{10})"),
    re.compile(r"comic-pile-factory-fix-(?:claim|progress)-v3:[^:>]+:[^:>]+:(\d{10})"),
    re.compile(r"comic-pile-factory-review-claim-v2:[^:>]+:[^:>]+:(\d{10})"),
)
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
__all__ = ["linked_issue_from_branch", "plan_distinct_assignments"]


def run_gh(args: list[str], *, input_json: object | None = None, check: bool = True) -> str:
    """Run a bounded GitHub CLI command and return stdout."""
    command = ['gh', *args]
    try:
        proc = subprocess.run(command, input=None if input_json is None else json.dumps(input_json), text=True, capture_output=True, check=False, timeout=GH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{' '.join(command)} timed out") from exc
    if check and proc.returncode:
        raise RuntimeError(f"{' '.join(command)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def gh_json(args: list[str], *, input_json: object | None = None) -> object | None:
    """Run GitHub CLI and decode its JSON output."""
    output = run_gh(args, input_json=input_json)
    return json.loads(output) if output.strip() else None


def list_issues() -> list[dict[str, Any]]:
    """List open issues visible to the assignment controller."""
    return cast(list[dict[str, Any]], gh_json(['issue', 'list', '--repo', REPO, '--state', 'open', '--limit', '1000', '--json', 'number,title,labels,createdAt,updatedAt']))


def list_prs() -> list[dict[str, Any]]:
    """List open pull requests visible to the assignment controller."""
    return cast(list[dict[str, Any]], gh_json(['pr', 'list', '--repo', REPO, '--state', 'open', '--limit', '500', '--json', 'number,title,body,labels,headRefName,createdAt,updatedAt,isDraft']))


def target_json(number: int) -> dict[str, Any]:
    """Fetch one issue-compatible GitHub target payload."""
    return cast(dict[str, Any], gh_json(['api', f'repos/{REPO}/issues/{number}']))


def replace_factory_labels(number: int, owner: str, stage: str | None=None) -> None:
    """Atomically reconcile one target to exactly one owner and workflow stage.

    The repository policy requires a single full label-set replacement rather
    than sequential add/remove mutations, which would expose contradictory
    intermediate owner states. A post-write claim verification is performed by
    ``assign_candidate``.
    """
    target = target_json(number)
    current = [label['name'] for label in target.get('labels', [])]
    existing_stage = next((label for label in current if label in STAGE_LABELS), None)
    stage = stage or existing_stage or 'factory:building'
    labels = [label for label in current if not OWNER_RE.fullmatch(label) and label not in STAGE_LABELS and (label != 'factory')]
    labels.extend(['factory', owner, stage])
    run_gh(['api', '--method', 'PUT', f'repos/{REPO}/issues/{number}/labels', '--input', '-'], input_json={'labels': sorted(set(labels))})


def issue_has_open_blocker(number: int) -> bool:
    """Return whether an issue has an open dependency blocker."""
    try:
        blockers = cast(list[dict[str, Any]], gh_json(['api', f'repos/{REPO}/issues/{number}/dependencies/blocked_by?per_page=100']) or [])
    except RuntimeError:
        return True
    return any(item.get('state') == 'open' for item in blockers)


def required_checks_failed(pr_number: int) -> bool:
    """Return whether any required pull-request check has failed."""
    try:
        output = run_gh(['pr', 'checks', str(pr_number), '--repo', REPO, '--required', '--json', 'state'], check=False)
    except RuntimeError:
        return False
    if not output.strip():
        return False
    try:
        checks = cast(list[dict[str, Any]], json.loads(output))
    except json.JSONDecodeError:
        return False
    failure_states = {'FAILURE', 'ERROR', 'CANCELLED', 'TIMED_OUT', 'ACTION_REQUIRED', 'STARTUP_FAILURE'}
    return any(str(check.get('state', '')).upper() in failure_states for check in checks)


def candidate_is_live_executable(candidate: Candidate) -> bool:
    """Return whether a ranked candidate has an executable next action."""
    if candidate.kind == 'issue':
        return not issue_has_open_blocker(candidate.number)
    target = target_json(candidate.number)
    labels = {label['name'] for label in target.get('labels', [])}
    if 'factory:ci' in labels:
        return required_checks_failed(candidate.number)
    return True


def target_still_unowned(number: int) -> bool:
    """Return whether a target remains safely claimable."""
    labels = {label['name'] for label in target_json(number).get('labels', [])}
    return item_is_unowned(labels) and not bool(labels & BLOCKED_LABELS)


def target_owned_by(number: int, owner: str) -> bool:
    """Return whether exactly one expected active owner holds a target."""
    labels = {label['name'] for label in target_json(number).get('labels', [])}
    active_owners = {label for label in labels if OWNER_RE.fullmatch(label) and label != 'factory:unowned'}
    return active_owners == {owner}


def assign_candidate(candidate: Candidate, worker: str) -> bool:
    """Claim a candidate and any linked issue for one fixed-model worker."""
    owner = f'factory:{worker}'
    numbers = [candidate.number]
    if candidate.kind == 'pr' and candidate.linked_issue is not None:
        try:
            issue = target_json(candidate.linked_issue)
        except RuntimeError:
            issue = None
        if issue and issue.get('state') == 'open':
            numbers.insert(0, candidate.linked_issue)
    for number in numbers:
        if not target_still_unowned(number):
            return False

    def release_verified_claims(claimed_numbers: list[int]) -> None:
        """Release only labels this worker can still prove it owns."""
        for claimed_number in claimed_numbers:
            try:
                if target_owned_by(claimed_number, owner):
                    replace_factory_labels(claimed_number, 'factory:unowned')
            except Exception:
                pass
    claimed: list[int] = []
    try:
        for number in numbers:
            stage = 'factory:building' if candidate.kind == 'issue' else None
            replace_factory_labels(number, owner, stage)
            if not target_owned_by(number, owner):
                release_verified_claims(claimed)
                return False
            claimed.append(number)
    except Exception:
        release_verified_claims(claimed)
        raise
    return True


def flatten_pages(pages: object | None) -> list[dict[str, Any]]:
    """Flatten paginated GitHub API responses into object rows."""
    result: list[dict[str, Any]] = []
    for page in pages or []:
        if isinstance(page, list):
            result.extend(item for item in page if isinstance(item, dict))
        elif isinstance(page, dict):
            result.append(page)
    return result


def latest_lease_activity_epoch(number: int) -> int | None:
    """Return the latest trusted lease activity marker for a target."""
    try:
        pages = gh_json(['api', '--paginate', '--slurp', f'repos/{REPO}/issues/{number}/comments?per_page=100'])
    except RuntimeError:
        return None
    latest: int | None = None
    for comment in flatten_pages(pages):
        if comment.get('author_association') not in TRUSTED_ASSOCIATIONS:
            continue
        body = str(comment.get('body') or '')
        for pattern in LEASE_ACTIVITY_PATTERNS:
            for match in pattern.findall(body):
                epoch = int(match)
                latest = epoch if latest is None else max(latest, epoch)
    return latest


def active_fixed_workers() -> set[int]:
    """Return worker IDs with queued or running fixed-model entry runs."""
    workers: set[int] = set()
    runs: list[dict[str, Any]] = []
    for status in ('queued', 'in_progress'):
        pages = gh_json(['api', '--paginate', '--slurp', f'repos/{REPO}/actions/workflows/free-model-factory-entry.yml/runs?status={status}&per_page=100'])
        for page in pages or []:
            if isinstance(page, dict):
                runs.extend(page.get('workflow_runs', []))
    unresolved_run_ids: set[str] = set()
    for run in runs:
        title = str(run.get('display_title') or run.get('name') or '')
        match = re.search('\\bFactory\\s+(\\d+)\\b', title)
        if match:
            workers.add(int(match.group(1)))
        else:
            run_id = str(run.get('id') or '')
            if run_id:
                unresolved_run_ids.add(run_id)
    if unresolved_run_ids:
        pages = gh_json(['api', '--paginate', '--slurp', f'repos/{REPO}/issues/1093/comments?per_page=100'])
        for comment in flatten_pages(pages):
            if comment.get('author_association') not in TRUSTED_ASSOCIATIONS:
                continue
            body = str(comment.get('body') or '')
            run_match = re.search('(?m)^Run:\\s*(\\d+)\\s*$', body)
            worker_match = re.search('(?m)^Worker:\\s*opencode-free-model-factory-(\\d+)\\s*$', body)
            if run_match and worker_match and (run_match.group(1) in unresolved_run_ids):
                workers.add(int(worker_match.group(1)))
                unresolved_run_ids.discard(run_match.group(1))
    if unresolved_run_ids:
        raise RuntimeError('unable to resolve worker identity for active fixed-model runs: ' + ', '.join(sorted(unresolved_run_ids)))
    return workers


def owned_targets(issues: list[dict[str, Any]] | None=None, prs: list[dict[str, Any]] | None=None) -> list[tuple[int, str]]:
    """List open targets that currently have an active factory owner."""
    targets: list[tuple[int, str]] = []
    issue_items = list_issues() if issues is None else issues
    pr_items = list_prs() if prs is None else prs
    for item in [*issue_items, *pr_items]:
        owner = owner_of(labels_of(item))
        if owner and owner != 'factory:unowned':
            targets.append((int(item['number']), owner))
    return targets


def reconcile_stale_leases(now_epoch: int | None=None) -> list[int]:
    """Release fixed-model and proven-stale local leases safely."""
    now_epoch = int(time.time()) if now_epoch is None else now_epoch
    active = active_fixed_workers()
    released: list[int] = []
    for number, owner in owned_targets():
        activity = latest_lease_activity_epoch(number) if owner == 'factory:local' else None
        if not lease_is_stale(owner, active_fixed_workers=active, latest_activity_epoch=activity, now_epoch=now_epoch):
            continue
        replace_factory_labels(number, 'factory:unowned')
        released.append(number)
        print(f'[factory-controller] released stale {owner} lease on #{number}', file=sys.stderr)
    return released


def worker_has_active_lease(worker: str) -> bool:
    """Return whether a fixed-model worker already owns open work."""
    owner = f'factory:{worker}'
    return any(current_owner == owner for _, current_owner in owned_targets())


def assign(worker: str) -> Candidate | None:
    """Assign the highest-ranked executable work to one fixed-model worker."""
    if not re.fullmatch('(?:[6-9]|[1-3][0-9]|4[0-6])', worker):
        raise SystemExit(f'unsupported fixed-model worker: {worker}')
    if worker_has_active_lease(worker):
        print(f'[factory-controller] Factory {worker} already has an active lease; skipping dispatch', file=sys.stderr)
        return None
    candidates = order_candidates_for_worker(build_candidates(list_issues(), list_prs()), worker)
    for candidate in candidates:
        if not candidate_is_live_executable(candidate):
            continue
        if assign_candidate(candidate, worker):
            print(f'[factory-controller] assigned {candidate.kind} #{candidate.number} lane={candidate.lane} priority={candidate.priority} to Factory {worker}', file=sys.stderr)
            return candidate
    return None


def release_worker(worker: str) -> list[int]:
    """Release all targets still owned by one fixed-model worker."""
    owner = f'factory:{worker}'
    released: list[int] = []
    for number, current_owner in owned_targets():
        if current_owner != owner:
            continue
        replace_factory_labels(number, 'factory:unowned')
        released.append(number)
    return released


def main() -> int:
    """Run the factory controller command-line interface."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('reconcile')
    assign_parser = subparsers.add_parser('assign')
    assign_parser.add_argument('--worker', required=True)
    release_parser = subparsers.add_parser('release')
    release_parser.add_argument('--worker', required=True)
    args = parser.parse_args()
    if args.command == 'reconcile':
        print(json.dumps({'released': reconcile_stale_leases()}))
        return 0
    if args.command == 'assign':
        candidate = assign(args.worker)
        if candidate is None:
            print(json.dumps({'kind': 'none'}))
            return 0
        print(json.dumps({'kind': candidate.kind, 'number': candidate.number, 'lane': candidate.lane, 'priority': candidate.priority, 'linked_issue': candidate.linked_issue}))
        return 0
    print(json.dumps({'released': release_worker(args.worker)}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
