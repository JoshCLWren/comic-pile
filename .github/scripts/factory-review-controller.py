#!/usr/bin/env python3
"""Controller-owned semantic review authorization for ComicPile factory PRs."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, os.path.dirname(__file__))
from factory_review_policy import (  # noqa: E402
    approval_can_promote,
    current_head_approvers,
    head_has_authorized_approval,
    producer_worker_from_pr,
    review_marker,
)

REPO = os.environ.get("GITHUB_REPOSITORY", "JoshCLWren/comic-pile")
OWNER_RE = re.compile(r"^factory:(?:unowned|local|[1-9]|[1-3][0-9]|4[0-6])$")
STAGE_LABELS = {
    "factory:building",
    "factory:review",
    "factory:changes-requested",
    "factory:ci",
    "factory:ready",
    "factory:blocked",
}
FIXED_WORKER_RE = re.compile(r"^(?:[6-9]|[1-3][0-9]|4[0-6])$")
GH_TIMEOUT_SECONDS = 120


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


def labels_of_pr(pr: dict[str, Any]) -> set[str]:
    """Return normalized PR labels."""
    labels: set[str] = set()
    for label in pr.get("labels") or []:
        if isinstance(label, dict) and label.get("name"):
            labels.add(str(label["name"]))
        elif isinstance(label, str):
            labels.add(label)
    return labels


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


def replace_factory_labels(number: int, owner: str, stage: str) -> None:
    """Atomically replace factory owner/stage labels on one issue-compatible target."""
    target = target_json(number)
    current = [str(label["name"]) for label in target.get("labels", [])]
    labels = [
        label
        for label in current
        if not OWNER_RE.fullmatch(label)
        and label not in STAGE_LABELS
        and label != "factory"
    ]
    labels.extend(["factory", owner, stage])
    run_gh(
        [
            "api",
            "--method",
            "PUT",
            f"repos/{REPO}/issues/{number}/labels",
            "--input",
            "-",
        ],
        input_json={"labels": sorted(set(labels))},
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
    for page in value or []:
        if isinstance(page, list):
            result.extend(item for item in page if isinstance(item, dict))
        elif isinstance(page, dict):
            result.append(page)
    return result


def review_comment_bodies(pr_number: int) -> list[str]:
    """Return comment bodies that can contain controller semantic attestations."""
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


def review_excerpt(path: str | None) -> str:
    """Read a bounded tail of model review output for actionable findings."""
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-7000:]


def post_review_comment(
    *,
    pr_number: int,
    marker: str | None,
    reviewer: str,
    verdict: str,
    excerpt: str,
    note: str = "",
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


def current_head_review_blockers(pr_number: int, head: str) -> bool:
    """Return True when the current head has no blocking reviews or threads."""
    pages = gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            f"repos/{REPO}/pulls/{pr_number}/reviews?per_page=100",
        ]
    )
    for review in flatten_pages(pages):
        if review.get("state") == "CHANGES_REQUESTED" and review.get("commit_id") == head:
            return False

    owner, name = REPO.split("/", 1)
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
                    "reviewThreads(first:100){nodes{isResolved}}}}}"
                ),
            ]
        ),
    )
    nodes = (
        result.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes", [])
    )
    return not any(not bool(node.get("isResolved")) for node in nodes)


def mechanical_merge_gates_pass(pr_number: int, expected_head: str) -> bool:
    """Re-check exact-head mechanical gates without trusting model output."""
    info = pr_json(pr_number)
    if str(info.get("state")) != "OPEN":
        return False
    if bool(info.get("isDraft")):
        return False
    if str(info.get("mergeable")) != "MERGEABLE":
        return False
    head = str(info.get("headRefOid") or "")
    if not head or head != expected_head:
        return False
    checks = run_gh(
        ["pr", "checks", str(pr_number), "--repo", REPO, "--required"],
        check=False,
    )
    if checks.returncode:
        return False
    return current_head_review_blockers(pr_number, head)


def target_owned_by_worker(number: int, worker: str) -> bool:
    """Return whether the target is currently leased to exactly this worker."""
    labels = {
        str(label["name"])
        for label in target_json(number).get("labels", [])
        if isinstance(label, dict) and label.get("name")
    }
    active = {
        label
        for label in labels
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
    """Release a reviewed PR and its linked issue to controller-owned lifecycle state."""
    replace_factory_labels(pr_number, "factory:unowned", pr_stage)
    issue = linked_issue_from_branch(branch)
    if issue is None:
        return
    try:
        state = target_json(issue)
    except RuntimeError:
        return
    if state.get("state") != "open":
        return
    if not target_owned_by_worker(issue, worker):
        return
    replace_factory_labels(issue, "factory:unowned", issue_stage or pr_stage)


def validate_review_lease(pr_number: int, worker: str, pr: dict[str, Any]) -> None:
    """Reject review state changes that are not backed by the current lease."""
    if str(pr.get("state")) != "OPEN":
        raise RuntimeError(f"PR #{pr_number} is not open")
    labels = labels_of_pr(pr)
    if "factory:review" not in labels:
        raise RuntimeError(f"PR #{pr_number} is not in factory:review")
    if f"factory:{worker}" not in labels or not target_owned_by_worker(pr_number, worker):
        raise RuntimeError(f"PR #{pr_number} is not exclusively leased to Factory {worker}")


def handle_review(
    *,
    worker: str,
    pr_number: int,
    verdict: str,
    review_log: str | None,
) -> dict[str, Any]:
    """Interpret semantic model output under controller-owned repository authority."""
    if not FIXED_WORKER_RE.fullmatch(worker):
        raise RuntimeError(f"unsupported fixed-model reviewer: {worker}")
    if verdict not in {"approve", "repair", "reject"}:
        raise RuntimeError(f"unsupported semantic verdict: {verdict}")

    pr = pr_json(pr_number)
    validate_review_lease(pr_number, worker, pr)
    branch = str(pr.get("headRefName") or "")
    head = str(pr.get("headRefOid") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RuntimeError(f"PR #{pr_number} has an invalid current head")
    producer = producer_worker_from_pr(branch=branch, body=str(pr.get("body") or ""))
    excerpt = review_excerpt(review_log)

    if verdict == "repair":
        marker = review_marker(
            pr=pr_number,
            head=head,
            reviewer=worker,
            producer=producer,
            verdict=verdict,
        )
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
        return {"status": "repair", "head": head, "producer": producer}

    if verdict == "reject":
        marker = review_marker(
            pr=pr_number,
            head=head,
            reviewer=worker,
            producer=producer,
            verdict=verdict,
        )
        post_review_comment(
            pr_number=pr_number,
            marker=marker,
            reviewer=worker,
            verdict=verdict,
            excerpt=excerpt,
            note=(
                "The reviewer classified this factory PR as unsalvageable. "
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
        return {"status": "rejected", "head": head, "producer": producer}

    if producer is not None and producer == worker:
        post_review_comment(
            pr_number=pr_number,
            marker=None,
            reviewer=worker,
            verdict=verdict,
            excerpt=excerpt,
            note=(
                "Approval was ignored because the reviewer is the producing factory. "
                "A different factory must review this exact head."
            ),
        )
        transition_pr_and_linked_issue(
            pr_number=pr_number,
            branch=branch,
            worker=worker,
            pr_stage="factory:review",
        )
        return {
            "status": "self-review-blocked",
            "head": head,
            "producer": producer,
        }

    prior_approvers = current_head_approvers(
        review_comment_bodies(pr_number),
        pr=pr_number,
        head=head,
    )
    marker = review_marker(
        pr=pr_number,
        head=head,
        reviewer=worker,
        producer=producer,
        verdict=verdict,
    )
    post_review_comment(
        pr_number=pr_number,
        marker=marker,
        reviewer=worker,
        verdict=verdict,
        excerpt=excerpt,
        note="Semantic approval is scoped to this exact PR head.",
    )

    mechanical = mechanical_merge_gates_pass(pr_number, head)
    current = pr_json(pr_number)
    current_head = str(current.get("headRefOid") or "")
    authorized = approval_can_promote(
        producer=producer,
        reviewer=worker,
        reviewed_head=head,
        current_head=current_head,
        verdict=verdict,
        mechanical_gates_passed=mechanical,
        prior_approvers=prior_approvers,
    )
    if not authorized:
        note = (
            "Historical producer provenance is unavailable, so one additional "
            "distinct factory approval is required for this exact head."
            if producer is None and mechanical
            else "Approval did not satisfy all controller-side exact-head and mechanical gates."
        )
        post_review_comment(
            pr_number=pr_number,
            marker=None,
            reviewer=worker,
            verdict=verdict,
            excerpt="",
            note=note,
        )
        transition_pr_and_linked_issue(
            pr_number=pr_number,
            branch=branch,
            worker=worker,
            pr_stage="factory:review",
        )
        return {
            "status": "approved-not-ready",
            "head": head,
            "producer": producer,
            "mechanical": mechanical,
        }

    transition_pr_and_linked_issue(
        pr_number=pr_number,
        branch=branch,
        worker=worker,
        pr_stage="factory:ready",
    )
    return {
        "status": "ready",
        "head": head,
        "producer": producer,
        "mechanical": True,
    }


def authorize_ready(pr_number: int) -> dict[str, Any]:
    """Validate that a ready PR still has semantic authorization for its current head."""
    pr = pr_json(pr_number)
    branch = str(pr.get("headRefName") or "")
    head = str(pr.get("headRefOid") or "")
    labels = labels_of_pr(pr)
    producer = producer_worker_from_pr(branch=branch, body=str(pr.get("body") or ""))
    approvers = current_head_approvers(
        review_comment_bodies(pr_number),
        pr=pr_number,
        head=head,
    )
    authorized = (
        str(pr.get("state")) == "OPEN"
        and "factory:ready" in labels
        and head_has_authorized_approval(producer=producer, approvers=approvers)
    )
    if authorized:
        return {
            "authorized": True,
            "head": head,
            "producer": producer,
            "approvers": sorted(approvers),
        }

    if str(pr.get("state")) == "OPEN" and "factory:ready" in labels:
        replace_factory_labels(pr_number, "factory:unowned", "factory:review")
        issue = linked_issue_from_branch(branch)
        if issue is not None:
            try:
                issue_target = target_json(issue)
            except RuntimeError:
                issue_target = None
            if issue_target and issue_target.get("state") == "open":
                issue_labels = {
                    str(label["name"])
                    for label in issue_target.get("labels", [])
                    if isinstance(label, dict) and label.get("name")
                }
                if "factory:ready" in issue_labels:
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
    review.add_argument(
        "--verdict",
        choices=("approve", "repair", "reject"),
        required=True,
    )
    review.add_argument("--review-log")

    authorized = subparsers.add_parser("authorized")
    authorized.add_argument("--pr", type=int, required=True)

    args = parser.parse_args()
    if args.command == "review":
        result = handle_review(
            worker=args.worker,
            pr_number=args.pr,
            verdict=args.verdict,
            review_log=args.review_log,
        )
    else:
        result = authorize_ready(args.pr)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
