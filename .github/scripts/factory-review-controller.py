#!/usr/bin/env python3
"""Controller-owned semantic review authorization and mechanical merge gates."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

sys.path.insert(0, os.path.dirname(__file__))
_review_policy = importlib.import_module("factory_review_policy")
approval_can_promote = _review_policy.approval_can_promote
current_head_approvers = _review_policy.current_head_approvers
classify_ci_reconciliation = _review_policy.classify_ci_reconciliation
head_has_authorized_approval = _review_policy.head_has_authorized_approval
producer_worker_from_pr = _review_policy.producer_worker_from_pr
review_marker = _review_policy.review_marker

REPO = os.environ.get("GITHUB_REPOSITORY", "JoshCLWren/comic-pile")
OWNER_RE = re.compile(r"^factory:(?:unowned|local|[1-9]|[1-3][0-9]|[4-6][0-9])$")
FIXED_WORKER_RE = re.compile(r"^(?:[6-9]|[1-3][0-9]|[4-6][0-9])$")
HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)([\"']?[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|DATABASE_URL|REDIS_URL|POSTGRES_URL)[\"']?\s*[=:]\s*[\"']?)([^\"'\s,}]+)"
)
BEARER_RE = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)\S+")
GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")
API_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
STAGE_LABELS = {
    "factory:building",
    "factory:review",
    "factory:changes-requested",
    "factory:ci",
    "factory:ready",
    "factory:blocked",
}
GH_TIMEOUT_SECONDS = 120
MERGEABLE_POLL_ATTEMPTS = 10
MERGEABLE_POLL_INTERVAL_SECONDS = 2.0
PASSING_CHECK_STATES = {"SUCCESS", "SKIPPED", "NEUTRAL"}
RETRY_CHECK_STATES = {
    "ACTION_REQUIRED",
    "EXPECTED",
    "IN_PROGRESS",
    "PENDING",
    "QUEUED",
    "REQUESTED",
    "WAITING",
}
FAILING_CHECK_STATES = {
    "CANCELLED",
    "ERROR",
    "FAILURE",
    "STALE",
    "STARTUP_FAILURE",
    "TIMED_OUT",
}
NO_REQUIRED_CHECKS_RE = re.compile(r"no checks reported|no required checks", re.IGNORECASE)
NO_REQUIRED_CHECKS_REASON = (
    "no required checks reported at this head; merge is blocked until CI runs and passes"
)

GateDecision = Literal["pass", "retry", "deny"]


class GateResult(TypedDict):
    decision: GateDecision
    reason: str


def gate_result(decision: GateDecision, reason: str) -> GateResult:
    return {"decision": decision, "reason": reason}


def run_gh(
    args: list[str],
    *,
    input_json: object | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run one bounded GitHub CLI command."""
    command = ["gh", *args]
    try:
        proc = subprocess.run(
            command,
            input=None if input_json is None else json.dumps(input_json),
            text=True,
            capture_output=True,
            check=False,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{' '.join(command)} timed out") from exc
    if check and proc.returncode:
        raise RuntimeError(
            f"{' '.join(command)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc


def gh_json(args: list[str], *, input_json: object | None = None) -> object | None:
    """Run GitHub CLI and decode JSON stdout."""
    output = run_gh(args, input_json=input_json).stdout
    return json.loads(output) if output.strip() else None


def pr_json(pr_number: int) -> dict[str, Any]:
    """Fetch authoritative current PR state."""
    return cast(
        dict[str, Any],
        gh_json(
            [
                "pr",
                "view",
                str(pr_number),
                "--repo",
                REPO,
                "--json",
                "state,isDraft,mergeable,headRefOid,headRefName,body,labels",
            ]
        ),
    )


def target_json(number: int) -> dict[str, Any]:
    """Fetch issue-compatible target state."""
    return cast(dict[str, Any], gh_json(["api", f"repos/{REPO}/issues/{number}"]))


def labels_of(item: dict[str, Any]) -> set[str]:
    """Return normalized label names from a GitHub payload."""
    labels: set[str] = set()
    for label in item.get("labels") or []:
        if isinstance(label, dict) and label.get("name"):
            labels.add(str(label["name"]))
        elif isinstance(label, str):
            labels.add(label)
    return labels


def replace_factory_labels(number: int, owner: str, stage: str) -> None:
    """Atomically replace factory owner/stage labels on one target."""
    current = labels_of(target_json(number))
    labels = {
        label
        for label in current
        if not OWNER_RE.fullmatch(label)
        and label not in STAGE_LABELS
        and label != "factory"
    }
    labels.update({"factory", owner, stage})
    run_gh(
        [
            "api",
            "--method",
            "PUT",
            f"repos/{REPO}/issues/{number}/labels",
            "--input",
            "-",
        ],
        input_json={"labels": sorted(labels)},
    )


def linked_issue_from_branch(branch: str | None) -> int | None:
    """Extract an issue number from a canonical fixed-model branch."""
    if not branch:
        return None
    match = re.match(r"^factory/\d+-(\d+)-", branch)
    return int(match.group(1)) if match else None


def flatten_pages(value: object | None) -> list[dict[str, Any]]:
    """Flatten gh api --paginate --slurp JSON pages."""
    result: list[dict[str, Any]] = []
    pages = value if isinstance(value, list) else []
    for page in pages:
        if isinstance(page, list):
            result.extend(item for item in page if isinstance(item, dict))
        elif isinstance(page, dict):
            result.append(page)
    return result


def review_comment_bodies(pr_number: int) -> list[str]:
    """Return action-authored comments that may contain review attestations."""
    pages = gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            f"repos/{REPO}/issues/{pr_number}/comments?per_page=100",
        ]
    )
    bodies: list[str] = []
    for comment in flatten_pages(pages):
        user = comment.get("user") or {}
        if not isinstance(user, dict) or user.get("login") != "github-actions[bot]":
            continue
        bodies.append(str(comment.get("body") or ""))
    return bodies


def redact_review_text(text: str) -> str:
    """Redact common credential shapes before review output reaches GitHub."""
    text = SENSITIVE_ASSIGNMENT_RE.sub(r"\1[REDACTED]", text)
    text = BEARER_RE.sub(r"\1[REDACTED]", text)
    text = GITHUB_TOKEN_RE.sub("[REDACTED_GITHUB_TOKEN]", text)
    return API_KEY_RE.sub("[REDACTED_API_KEY]", text)


def review_excerpt(path: str | None, *, worker: str) -> str:
    """Read only the expected worker log and return a redacted bounded tail."""
    if not path:
        return ""
    expected = Path(f"/tmp/opencode-factory-{worker}.log")
    candidate = Path(path)
    if candidate != expected or candidate.is_symlink():
        return ""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8", errors="replace") as stream:
            text = stream.read()
    except OSError:
        return ""
    return redact_review_text(text[-7000:])


def post_review_comment(
    *,
    pr_number: int,
    marker: str | None,
    reviewer: str,
    verdict: str,
    excerpt: str,
    note: str,
) -> None:
    """Persist semantic findings and controller audit metadata."""
    parts: list[str] = []
    if marker:
        parts.append(marker)
    parts.append(f"### Factory semantic review · Factory {reviewer} · {verdict.upper()}")
    if note:
        parts.append(note)
    if excerpt:
        parts.append(
            "<details><summary>Review output</summary>\n\n```text\n"
            + excerpt
            + "\n```\n</details>"
        )
    run_gh(
        ["issue", "comment", str(pr_number), "--repo", REPO, "--body", "\n\n".join(parts)]
    )


def interpret_required_checks(
    checks: object | None,
    *,
    command_status: int,
    stderr: str,
) -> GateResult:
    """Pure interpretation of `gh pr checks --required --json state` output.

    Fail-closed: a head with no reported required checks has not been
    validated, so it can never satisfy the merge gates.
    """
    del command_status
    if checks is None:
        if NO_REQUIRED_CHECKS_RE.search(stderr):
            return gate_result("retry", NO_REQUIRED_CHECKS_REASON)
        return gate_result("retry", "required checks could not be determined")
    if not isinstance(checks, list):
        return gate_result("retry", "required check payload was not a list")
    if not checks:
        return gate_result("retry", NO_REQUIRED_CHECKS_REASON)

    states: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            return gate_result("retry", "required check payload contained an invalid row")
        state = str(check.get("state") or "").upper()
        if not state:
            return gate_result("retry", "required check state was missing")
        states.append(state)

    failing = sorted(set(states) & FAILING_CHECK_STATES)
    if failing:
        return gate_result("deny", f"required checks failed: {', '.join(failing)}")
    waiting = sorted(set(states) & RETRY_CHECK_STATES)
    if waiting:
        return gate_result("retry", f"required checks are not terminal: {', '.join(waiting)}")
    unknown = sorted(set(states) - PASSING_CHECK_STATES)
    if unknown:
        return gate_result("retry", f"unknown required check states: {', '.join(unknown)}")
    return gate_result("pass", "all required checks are successful")


def required_checks_gate(pr_number: int) -> GateResult:
    proc = run_gh(
        ["pr", "checks", str(pr_number), "--repo", REPO, "--required", "--json", "state"],
        check=False,
    )
    checks: object | None = None
    if proc.stdout.strip():
        try:
            checks = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return gate_result("retry", "required checks returned invalid JSON")
    return interpret_required_checks(checks, command_status=proc.returncode, stderr=proc.stderr)


def list_ci_pr_numbers() -> list[int]:
    """List open CI-stage factory PRs for deterministic reconciliation."""
    rows = gh_json(
        [
            "pr",
            "list",
            "--repo",
            REPO,
            "--state",
            "open",
            "--label",
            "factory:ci",
            "--limit",
            "500",
            "--json",
            "number",
        ]
    )
    if not isinstance(rows, list):
        raise RuntimeError("factory:ci PR listing was unavailable")
    return [int(row["number"]) for row in rows if isinstance(row, dict) and row.get("number")]


def active_factory_owner(labels: set[str]) -> str | None:
    """Return an active owner, ignoring the explicit unowned marker."""
    owners = {label for label in labels if OWNER_RE.fullmatch(label)}
    active = owners - {"factory:unowned"}
    return sorted(active)[0] if active else None


def reconcile_ci_pr(pr_number: int) -> dict[str, Any]:
    """Reconcile one unowned CI PR using exact-head controller authorities."""
    pr = pr_json(pr_number)
    labels = labels_of(pr)
    if str(pr.get("state")) != "OPEN" or "factory:ci" not in labels:
        return {"pr": pr_number, "status": "skipped"}
    if active_factory_owner(labels) is not None:
        return {"pr": pr_number, "status": "owned"}

    checks = required_checks_gate(pr_number)
    if checks["decision"] != "pass":
        status = classify_ci_reconciliation(
            checks_decision=checks["decision"], authorized=False
        )
        return {"pr": pr_number, "status": status, "reason": checks["reason"]}

    head = str(pr.get("headRefOid") or "")
    branch = str(pr.get("headRefName") or "")
    if not HEAD_RE.fullmatch(head):
        return {"pr": pr_number, "status": "retry-ci", "reason": "current head unavailable"}

    producer = producer_worker_from_pr(branch=branch, body=str(pr.get("body") or ""))
    try:
        approvers = current_head_approvers(
            review_comment_bodies(pr_number), pr=pr_number, head=head
        )
    except (RuntimeError, json.JSONDecodeError) as exc:
        return {
            "pr": pr_number,
            "status": "retry-ci",
            "reason": f"semantic authorization could not be determined: {exc}",
        }
    authorized = head_has_authorized_approval(producer=producer, approvers=approvers)
    if not authorized:
        replace_factory_labels(pr_number, "factory:unowned", "factory:review")
        return {"pr": pr_number, "status": "review", "head": head}

    mechanical = mechanical_merge_gate(pr_number, head)
    current_head = str(pr_json(pr_number).get("headRefOid") or "")
    if current_head != head:
        replace_factory_labels(pr_number, "factory:unowned", "factory:review")
        return {"pr": pr_number, "status": "review", "head": current_head}

    status = classify_ci_reconciliation(
        checks_decision=checks["decision"],
        authorized=True,
        mechanical_decision=mechanical["decision"],
    )
    if status == "ready":
        replace_factory_labels(pr_number, "factory:unowned", "factory:ready")
    elif status == "changes-requested":
        replace_factory_labels(pr_number, "factory:unowned", "factory:changes-requested")
    return {
        "pr": pr_number,
        "status": status,
        "head": head,
        "reason": mechanical["reason"],
    }


def reconcile_ci() -> list[dict[str, Any]]:
    """Reconcile every currently open, unowned factory:ci PR."""
    results: list[dict[str, Any]] = []
    for pr_number in list_ci_pr_numbers():
        try:
            result = reconcile_ci_pr(pr_number)
        except (RuntimeError, json.JSONDecodeError) as exc:
            result = {"pr": pr_number, "status": "retry-ci", "reason": str(exc)}
            print(json.dumps(result, sort_keys=True), file=sys.stderr)
            raise
        results.append(result)
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
    return results


def interpret_review_threads(
    nodes: object | None,
    *,
    head: str,
    has_next_page: bool = False,
) -> GateResult:
    """Pure exact-head unresolved-thread interpretation."""
    if has_next_page:
        return gate_result("retry", "review thread pagination was incomplete")
    if not isinstance(nodes, list):
        return gate_result("retry", "review thread payload was unavailable")
    for node in nodes:
        if not isinstance(node, dict):
            return gate_result("retry", "review thread payload contained an invalid row")
        if bool(node.get("isResolved")):
            continue
        comments = node.get("comments")
        if not isinstance(comments, dict):
            return gate_result("retry", "unresolved review thread lacked comment metadata")
        if bool((comments.get("pageInfo") or {}).get("hasNextPage")):
            return gate_result("retry", "review thread comments were only partially inspected")
        comment_nodes = comments.get("nodes")
        if not isinstance(comment_nodes, list) or not comment_nodes:
            return gate_result("retry", "unresolved review thread lacked commit metadata")
        saw_commit = False
        for comment in comment_nodes:
            if not isinstance(comment, dict):
                return gate_result("retry", "review thread comment metadata was invalid")
            commit = comment.get("commit")
            if not isinstance(commit, dict) or not commit.get("oid"):
                return gate_result("retry", "review thread comment lacked a commit SHA")
            saw_commit = True
            if str(commit["oid"]) == head:
                return gate_result("deny", "current head has an unresolved review thread")
        if not saw_commit:
            return gate_result("retry", "unresolved review thread could not be head-scoped")
    return gate_result("pass", "no current-head review thread blockers")


def review_thread_query_required(comments: object | None, *, head: str) -> GateResult | None:
    """Use REST review comments to decide whether GraphQL thread state is needed.

    A review thread cannot exist without at least one inline review comment. If REST
    proves every inline comment belongs to an older head, unresolved thread state
    cannot block the exact current head and the GraphQL query is unnecessary. A
    missing commit id fails closed by requiring the GraphQL query.
    """
    rows = flatten_pages(comments)
    for comment in rows:
        commit_id = comment.get("commit_id")
        if not commit_id or str(commit_id) == head:
            return None
    return gate_result("pass", "no current-head review thread blockers")


def current_head_review_gate(pr_number: int, head: str) -> GateResult:
    try:
        pages = gh_json(
            ["api", "--paginate", "--slurp", f"repos/{REPO}/pulls/{pr_number}/reviews?per_page=100"]
        )
    except RuntimeError as exc:
        detail = redact_review_text(str(exc))[-500:]
        return gate_result("retry", f"review submissions could not be inspected: {detail}")
    for review in flatten_pages(pages):
        if review.get("state") == "CHANGES_REQUESTED" and review.get("commit_id") == head:
            return gate_result("deny", "current head has CHANGES_REQUESTED")

    try:
        comment_pages = gh_json(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{REPO}/pulls/{pr_number}/comments?per_page=100",
            ]
        )
    except RuntimeError as exc:
        detail = redact_review_text(str(exc))[-500:]
        return gate_result("retry", f"review comments could not be inspected: {detail}")

    rest_result = review_thread_query_required(comment_pages, head=head)
    if rest_result is not None:
        return rest_result

    owner, name = REPO.split("/", 1)
    try:
        result = cast(
            dict[str, Any],
            gh_json(
                [
                    "api",
                    "graphql",
                    "-F",
                    f"owner={owner}",
                    "-F",
                    f"name={name}",
                    "-F",
                    f"number={pr_number}",
                    "-f",
                    (
                        "query($owner:String!,$name:String!,$number:Int!){"
                        "repository(owner:$owner,name:$name){pullRequest(number:$number){"
                        "reviewThreads(first:100){nodes{isResolved comments(first:100){"
                        "nodes{commit{oid}} pageInfo{hasNextPage}}} pageInfo{hasNextPage}}}}}"
                    ),
                ]
            ),
        )
    except RuntimeError as exc:
        detail = redact_review_text(str(exc))[-500:]
        return gate_result("retry", f"review threads could not be inspected: {detail}")
    threads = (
        result.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
    )
    return interpret_review_threads(
        threads.get("nodes"),
        head=head,
        has_next_page=bool((threads.get("pageInfo") or {}).get("hasNextPage")),
    )


def poll_mergeable_gate(
    pr_number: int,
    expected_head: str,
    *,
    poll_attempts: int = MERGEABLE_POLL_ATTEMPTS,
    poll_interval: float = MERGEABLE_POLL_INTERVAL_SECONDS,
) -> GateResult:
    """Poll GitHub's asynchronous mergeability computation for an exact head."""
    for attempt in range(max(1, poll_attempts)):
        try:
            info = pr_json(pr_number)
        except RuntimeError:
            return gate_result("retry", "pull request state could not be read")
        if str(info.get("state")) != "OPEN":
            return gate_result("deny", "pull request is not open")
        if bool(info.get("isDraft")):
            return gate_result("deny", "pull request is a draft")
        head = str(info.get("headRefOid") or "")
        if head != expected_head:
            return gate_result("deny", "pull request head changed after semantic review")
        mergeable = str(info.get("mergeable") or "UNKNOWN").upper()
        if mergeable == "MERGEABLE":
            return gate_result("pass", "pull request is mergeable")
        if mergeable == "CONFLICTING":
            return gate_result("deny", "pull request has merge conflicts")
        if mergeable != "UNKNOWN":
            return gate_result("retry", f"unrecognized mergeable state: {mergeable}")
        if attempt + 1 < max(1, poll_attempts):
            time.sleep(poll_interval)
    return gate_result("retry", "mergeability remained UNKNOWN after bounded polling")


def mechanical_merge_gate(pr_number: int, expected_head: str) -> GateResult:
    """Single authoritative exact-head mechanical gate for controller and workflows."""
    mergeable = poll_mergeable_gate(pr_number, expected_head)
    if mergeable["decision"] != "pass":
        return mergeable
    checks = required_checks_gate(pr_number)
    if checks["decision"] != "pass":
        return checks
    reviews = current_head_review_gate(pr_number, expected_head)
    if reviews["decision"] != "pass":
        return reviews
    return gate_result("pass", "all exact-head mechanical gates passed")


def mechanical_merge_gates_pass(pr_number: int, expected_head: str) -> bool:
    """Return whether the exact-head mechanical merge gate is green.

    This small compatibility wrapper keeps callers that only need a boolean
    decision separate from the controller's richer retry/deny result.
    """
    return mechanical_merge_gate(pr_number, expected_head)["decision"] == "pass"


def target_owned_by_worker(number: int, worker: str) -> bool:
    """Return whether exactly this fixed worker currently owns a target."""
    active = {
        label
        for label in labels_of(target_json(number))
        if OWNER_RE.fullmatch(label) and label != "factory:unowned"
    }
    return active == {f"factory:{worker}"}


def transition_pr_and_linked_issue(
    *,
    pr_number: int,
    branch: str,
    worker: str,
    pr_stage: str,
    issue_stage: str | None = None,
) -> None:
    """Release a reviewed PR and its linked issue to controller-owned state."""
    replace_factory_labels(pr_number, "factory:unowned", pr_stage)
    issue = linked_issue_from_branch(branch)
    if issue is None:
        return
    try:
        state = target_json(issue)
    except RuntimeError:
        return
    if state.get("state") != "open" or not target_owned_by_worker(issue, worker):
        return
    replace_factory_labels(issue, "factory:unowned", issue_stage or pr_stage)


def validate_review_lease(pr_number: int, worker: str, pr: dict[str, Any]) -> None:
    """Reject review state changes not backed by the current worker lease."""
    if str(pr.get("state")) != "OPEN":
        raise RuntimeError(f"PR #{pr_number} is not open")
    labels = labels_of(pr)
    if "factory:review" not in labels:
        raise RuntimeError(f"PR #{pr_number} is not in factory:review")
    if f"factory:{worker}" not in labels or not target_owned_by_worker(pr_number, worker):
        raise RuntimeError(f"PR #{pr_number} is not exclusively leased to Factory {worker}")


def return_to_review(
    *,
    pr_number: int,
    branch: str,
    worker: str,
    reviewer: str,
    verdict: str,
    excerpt: str,
    note: str,
    status: str,
    head: str,
    producer: str | None,
) -> dict[str, Any]:
    """Record a non-authoritative result and safely release its lease."""
    post_review_comment(
        pr_number=pr_number,
        marker=None,
        reviewer=reviewer,
        verdict=verdict,
        excerpt=excerpt,
        note=note,
    )
    transition_pr_and_linked_issue(
        pr_number=pr_number,
        branch=branch,
        worker=worker,
        pr_stage="factory:review",
    )
    return {"status": status, "head": head, "producer": producer}


def handle_review(
    *,
    worker: str,
    pr_number: int,
    verdict: str,
    reviewed_head: str,
    review_log: str | None,
) -> dict[str, Any]:
    """Interpret model review output under controller-owned repository authority."""
    if not FIXED_WORKER_RE.fullmatch(worker):
        raise RuntimeError(f"unsupported fixed-model reviewer: {worker}")
    if verdict not in {"approve", "repair", "reject"}:
        raise RuntimeError(f"unsupported semantic verdict: {verdict}")
    if not HEAD_RE.fullmatch(reviewed_head):
        raise RuntimeError("reviewed head must be a full lowercase Git SHA")

    pr = pr_json(pr_number)
    validate_review_lease(pr_number, worker, pr)
    branch = str(pr.get("headRefName") or "")
    current_head = str(pr.get("headRefOid") or "")
    if not HEAD_RE.fullmatch(current_head):
        raise RuntimeError(f"PR #{pr_number} has an invalid current head")
    producer = producer_worker_from_pr(branch=branch, body=str(pr.get("body") or ""))
    excerpt = review_excerpt(review_log, worker=worker)

    if current_head != reviewed_head:
        return return_to_review(
            pr_number=pr_number,
            branch=branch,
            worker=worker,
            reviewer=worker,
            verdict=verdict,
            excerpt=excerpt,
            note=(
                f"Verdict ignored because the reviewed checkout {reviewed_head} no longer "
                f"matches current head {current_head}. The new head requires fresh review."
            ),
            status="stale-head",
            head=current_head,
            producer=producer,
        )

    if producer is not None and producer == worker and verdict in {"approve", "reject"}:
        return return_to_review(
            pr_number=pr_number,
            branch=branch,
            worker=worker,
            reviewer=worker,
            verdict=verdict,
            excerpt=excerpt,
            note=(
                "Verdict ignored because the reviewer is the producing factory. "
                "A different factory must independently review this exact head."
            ),
            status="self-review-blocked",
            head=reviewed_head,
            producer=producer,
        )

    marker = review_marker(
        pr=pr_number,
        head=reviewed_head,
        reviewer=worker,
        producer=producer,
        verdict=verdict,
    )

    if verdict == "repair":
        post_review_comment(
            pr_number=pr_number,
            marker=marker,
            reviewer=worker,
            verdict=verdict,
            excerpt=excerpt,
            note="Semantic blockers remain. The PR is returning to repair.",
        )
        transition_pr_and_linked_issue(
            pr_number=pr_number,
            branch=branch,
            worker=worker,
            pr_stage="factory:changes-requested",
        )
        return {"status": "repair", "head": reviewed_head, "producer": producer}

    if verdict == "reject":
        post_review_comment(
            pr_number=pr_number,
            marker=marker,
            reviewer=worker,
            verdict=verdict,
            excerpt=excerpt,
            note=(
                "The independent reviewer classified this factory PR as unsalvageable. "
                "The linked issue remains available for a clean implementation."
            ),
        )
        transition_pr_and_linked_issue(
            pr_number=pr_number,
            branch=branch,
            worker=worker,
            pr_stage="factory:blocked",
            issue_stage="factory:building",
        )
        run_gh(["pr", "close", str(pr_number), "--repo", REPO])
        return {"status": "rejected", "head": reviewed_head, "producer": producer}

    prior_approvers = current_head_approvers(
        review_comment_bodies(pr_number),
        pr=pr_number,
        head=reviewed_head,
    )
    post_review_comment(
        pr_number=pr_number,
        marker=marker,
        reviewer=worker,
        verdict=verdict,
        excerpt=excerpt,
        note="Semantic approval is scoped to this exact reviewed PR head.",
    )

    mechanical_passed = mechanical_merge_gates_pass(pr_number, reviewed_head)
    mechanical: GateResult = {
        "decision": "pass" if mechanical_passed else "deny",
        "reason": "all exact-head mechanical gates passed"
        if mechanical_passed
        else "exact-head mechanical gates failed",
    }
    latest = pr_json(pr_number)
    latest_head = str(latest.get("headRefOid") or "")
    if mechanical["decision"] == "retry":
        result = return_to_review(
            pr_number=pr_number,
            branch=branch,
            worker=worker,
            reviewer=worker,
            verdict=verdict,
            excerpt="",
            note=(
                "Semantic approval is preserved for this exact head, but mechanical gates "
                f"are not yet decidable: {mechanical['reason']}. This is retry-later, not a denial."
            ),
            status="approved-deferred",
            head=latest_head or reviewed_head,
            producer=producer,
        )
        result["mechanical"] = mechanical
        return result

    mechanical_passed = mechanical["decision"] == "pass"
    authorized = approval_can_promote(
        producer=producer,
        reviewer=worker,
        reviewed_head=reviewed_head,
        current_head=latest_head,
        verdict=verdict,
        mechanical_gates_passed=mechanical_passed,
        prior_approvers=prior_approvers,
    )
    if not authorized:
        note = (
            "Historical producer provenance is unavailable, so one additional distinct "
            "factory approval is required for this exact head."
            if producer is None and mechanical_passed and latest_head == reviewed_head
            else f"Approval was denied by controller-side gates: {mechanical['reason']}."
        )
        result = return_to_review(
            pr_number=pr_number,
            branch=branch,
            worker=worker,
            reviewer=worker,
            verdict=verdict,
            excerpt="",
            note=note,
            status="approved-not-ready",
            head=latest_head or reviewed_head,
            producer=producer,
        )
        result["mechanical"] = mechanical
        return result

    transition_pr_and_linked_issue(
        pr_number=pr_number,
        branch=branch,
        worker=worker,
        pr_stage="factory:ready",
    )
    return {
        "status": "ready",
        "head": reviewed_head,
        "producer": producer,
        "mechanical": mechanical,
    }


def authorize_ready(pr_number: int) -> dict[str, Any]:
    """Validate that a ready PR still has authorization for its current head."""
    pr = pr_json(pr_number)
    branch = str(pr.get("headRefName") or "")
    head = str(pr.get("headRefOid") or "")
    producer = producer_worker_from_pr(branch=branch, body=str(pr.get("body") or ""))
    approvers = current_head_approvers(
        review_comment_bodies(pr_number),
        pr=pr_number,
        head=head,
    )
    authorized = (
        str(pr.get("state")) == "OPEN"
        and "factory:ready" in labels_of(pr)
        and HEAD_RE.fullmatch(head) is not None
        and head_has_authorized_approval(producer=producer, approvers=approvers)
    )
    if authorized:
        return {
            "authorized": True,
            "head": head,
            "producer": producer,
            "approvers": sorted(approvers),
        }

    if str(pr.get("state")) == "OPEN" and "factory:ready" in labels_of(pr):
        replace_factory_labels(pr_number, "factory:unowned", "factory:review")
        issue = linked_issue_from_branch(branch)
        if issue is not None:
            try:
                issue_target = target_json(issue)
            except RuntimeError:
                issue_target = None
            if (
                issue_target
                and issue_target.get("state") == "open"
                and "factory:ready" in labels_of(issue_target)
            ):
                replace_factory_labels(issue, "factory:unowned", "factory:review")

    return {
        "authorized": False,
        "head": head,
        "producer": producer,
        "approvers": sorted(approvers),
    }


def main() -> int:
    """Run semantic review controller commands."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("review")
    review.add_argument("--worker", required=True)
    review.add_argument("--pr", type=int, required=True)
    review.add_argument("--reviewed-head", required=True)
    review.add_argument(
        "--verdict",
        choices=("approve", "repair", "reject"),
        required=True,
    )
    review.add_argument("--review-log")

    authorized = subparsers.add_parser("authorized")
    authorized.add_argument("--pr", type=int, required=True)

    gates = subparsers.add_parser("gates")
    gates.add_argument("--pr", type=int, required=True)
    gates.add_argument("--expected-head", required=True)

    subparsers.add_parser("reconcile-ci")

    args = parser.parse_args()
    if args.command == "review":
        result = handle_review(
            worker=args.worker,
            pr_number=args.pr,
            verdict=args.verdict,
            reviewed_head=args.reviewed_head,
            review_log=args.review_log,
        )
    elif args.command == "authorized":
        result = authorize_ready(args.pr)
    elif args.command == "reconcile-ci":
        result = {"results": reconcile_ci()}
    else:
        if not HEAD_RE.fullmatch(args.expected_head):
            raise RuntimeError("expected head must be a full lowercase Git SHA")
        result = mechanical_merge_gate(args.pr, args.expected_head)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
