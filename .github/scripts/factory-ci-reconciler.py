#!/usr/bin/env python3
"""Advance passive factory CI states without spending a model worker."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast


REVIEW_CONTROLLER_PATH = Path(__file__).with_name("factory-review-controller.py")
BRANCH_ISSUE_RE = re.compile(r"^factory/\d+-(?P<issue>\d+)-")
FAILED_CHECKS_PREFIX = "required checks failed:"
REPAIR_DENY_REASONS = {
    "pull request has merge conflicts",
    "current head has CHANGES_REQUESTED",
    "current head has an unresolved review thread",
}
REVIEW_DENY_REASONS = {
    "pull request is a draft",
    "pull request head changed after semantic review",
}


def load_review_controller() -> ModuleType:
    """Load the existing exact-head review controller as the gate authority."""
    spec = importlib.util.spec_from_file_location(
        "factory_review_controller_for_ci_reconciliation",
        REVIEW_CONTROLLER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("factory review controller could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


review_controller = load_review_controller()


def list_ci_prs() -> list[int]:
    """Return every open pull request currently carrying the CI-stage label."""
    rows = cast(
        list[dict[str, Any]],
        review_controller.gh_json(
            [
                "pr",
                "list",
                "--repo",
                review_controller.REPO,
                "--state",
                "open",
                "--limit",
                "500",
                "--label",
                "factory:ci",
                "--json",
                "number",
            ]
        )
        or [],
    )
    return [int(row["number"]) for row in rows if row.get("number") is not None]


def active_factory_owner(labels: set[str]) -> str | None:
    """Return an active factory owner without treating unowned as a lease."""
    owners = sorted(
        label
        for label in labels
        if review_controller.OWNER_RE.fullmatch(label) and label != "factory:unowned"
    )
    return owners[0] if owners else None


def linked_issue_number(pr: dict[str, Any]) -> int | None:
    """Extract the canonical linked issue from a factory branch name."""
    match = BRANCH_ISSUE_RE.match(str(pr.get("headRefName") or ""))
    return int(match.group("issue")) if match else None


def linked_issue_lease_status(pr: dict[str, Any]) -> tuple[str, str | None] | None:
    """Return a blocking linked-issue lease state, if one exists."""
    issue_number = linked_issue_number(pr)
    if issue_number is None:
        return "linked-issue-indeterminate", None

    issue = cast(dict[str, Any], review_controller.target_json(issue_number))
    if str(issue.get("state") or "").upper() != "OPEN":
        return None

    labels = review_controller.labels_of(issue)
    owner = active_factory_owner(labels)
    if owner is not None:
        return "linked-issue-owned", owner
    if "factory:unowned" not in labels:
        return "linked-issue-owner-indeterminate", None
    return None


def exact_head_is_authorized(pr_number: int, pr: dict[str, Any]) -> bool:
    """Return whether semantic approval is valid for this exact current head."""
    branch = str(pr.get("headRefName") or "")
    head = str(pr.get("headRefOid") or "")
    producer = review_controller.producer_worker_from_pr(
        branch=branch,
        body=str(pr.get("body") or ""),
    )
    approvers = review_controller.current_head_approvers(
        review_controller.review_comment_bodies(pr_number),
        pr=pr_number,
        head=head,
    )
    return bool(
        review_controller.head_has_authorized_approval(
            producer=producer,
            approvers=approvers,
        )
    )


def reconcile_ci_pr(pr_number: int) -> dict[str, Any]:
    """Reconcile one CI-stage PR using existing exact-head authorization and gates."""
    pr = cast(dict[str, Any], review_controller.pr_json(pr_number))
    labels = review_controller.labels_of(pr)
    head = str(pr.get("headRefOid") or "")

    if str(pr.get("state") or "").upper() != "OPEN" or "factory:ci" not in labels:
        return {"pr": pr_number, "status": "not-ci", "head": head}

    owner = active_factory_owner(labels)
    if owner is not None:
        return {"pr": pr_number, "status": "owned", "owner": owner, "head": head}
    if "factory:unowned" not in labels:
        return {"pr": pr_number, "status": "owner-indeterminate", "head": head}

    linked_lease = linked_issue_lease_status(pr)
    if linked_lease is not None:
        status, linked_owner = linked_lease
        result: dict[str, Any] = {"pr": pr_number, "status": status, "head": head}
        if linked_owner is not None:
            result["owner"] = linked_owner
        return result

    if not review_controller.HEAD_RE.fullmatch(head):
        return {"pr": pr_number, "status": "head-indeterminate", "head": head}

    if not exact_head_is_authorized(pr_number, pr):
        review_controller.replace_factory_labels(
            pr_number,
            "factory:unowned",
            "factory:review",
        )
        return {
            "pr": pr_number,
            "status": "review",
            "head": head,
            "reason": "exact-head semantic approval is missing or stale",
        }

    gate = cast(
        dict[str, str],
        review_controller.mechanical_merge_gate(pr_number, head),
    )
    decision = str(gate.get("decision") or "retry")
    reason = str(gate.get("reason") or "mechanical gate result unavailable")

    if decision == "pass":
        review_controller.replace_factory_labels(
            pr_number,
            "factory:unowned",
            "factory:ready",
        )
        return {"pr": pr_number, "status": "ready", "head": head, "reason": reason}

    if decision == "retry":
        return {"pr": pr_number, "status": "ci", "head": head, "reason": reason}

    if decision == "deny" and reason.startswith(FAILED_CHECKS_PREFIX):
        return {
            "pr": pr_number,
            "status": "failed-ci",
            "head": head,
            "reason": reason,
        }

    if decision == "deny" and reason in REPAIR_DENY_REASONS:
        review_controller.replace_factory_labels(
            pr_number,
            "factory:unowned",
            "factory:changes-requested",
        )
        return {
            "pr": pr_number,
            "status": "changes-requested",
            "head": head,
            "reason": reason,
        }

    if decision == "deny" and reason in REVIEW_DENY_REASONS:
        review_controller.replace_factory_labels(
            pr_number,
            "factory:unowned",
            "factory:review",
        )
        return {"pr": pr_number, "status": "review", "head": head, "reason": reason}

    return {"pr": pr_number, "status": "ci", "head": head, "reason": reason}


def reconcile_all_ci_prs() -> list[dict[str, Any]]:
    """Reconcile all open CI-stage PRs independently and fail closed per PR."""
    results: list[dict[str, Any]] = []
    for pr_number in list_ci_prs():
        try:
            result = reconcile_ci_pr(pr_number)
        except Exception as exc:
            result = {
                "pr": pr_number,
                "status": "error",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        results.append(result)
        print(
            "[factory-ci-reconciler] " + json.dumps(result, sort_keys=True),
            file=sys.stderr,
        )
    return results


def main() -> int:
    """Run one passive CI reconciliation pass."""
    results = reconcile_all_ci_prs()
    print(json.dumps({"results": results}, sort_keys=True))
    return 1 if any(result.get("status") == "error" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
