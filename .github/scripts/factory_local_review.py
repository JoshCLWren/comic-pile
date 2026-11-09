"""Attest owner-submitted actual local review evidence from trusted Actions only."""
from __future__ import annotations

import importlib.util
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType


def load(name: str, filename: str) -> ModuleType:
    """Load a trusted sibling controller module."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


controller = load("local_review_controller", "factory-review-controller.py")
policy = controller._review_policy


def validate_lanes(payload: Mapping[str, object], head: str, contributors: set[str]) -> list[dict[str, object]]:
    """Require two truthful, independent completed local lanes, including actual Alpha."""
    lanes = payload.get("lanes")
    if not isinstance(lanes, list) or len(lanes) != 2:
        raise ValueError("two local review lanes required")
    identities: set[str] = set()
    validated: list[dict[str, object]] = []
    kinds: set[str] = set()
    for lane in lanes:
        if not isinstance(lane, dict):
            raise ValueError("malformed local lane")
        identity = lane.get("identity")
        if not isinstance(identity, str) or not re.fullmatch(r"local-[a-z0-9-]{3,80}", identity):
            raise ValueError("truthful local reviewer identity required")
        if identity in contributors or identity in identities:
            raise ValueError("reviewer authored this PR or lanes share an identity")
        identities.add(identity)
        if lane.get("head") != head or lane.get("verdict") != "approve":
            raise ValueError("stale or nonpassing local review")
        report = lane.get("report")
        model = lane.get("model")
        if not isinstance(report, str) or len(report.strip()) < 80 or not isinstance(model, str):
            raise ValueError("actual report and model required")
        kind = lane.get("kind")
        if kind == "alpha-acp":
            if model != "openrouter/stealth/crouton-alpha":
                raise ValueError("owner-selected Alpha model required")
            if lane.get("state") != "complete" or lane.get("model_confirmed") is not True:
                raise ValueError("Alpha completion and confirmed model required")
            if not lane.get("session") or not report.rstrip().endswith("FACTORY_GATE_READY"):
                raise ValueError("actual Alpha session and passing final report required")
        elif kind != "codex":
            raise ValueError("unknown local review lane")
        kinds.add(kind)
        validated.append(lane)
    if kinds != {"alpha-acp", "codex"}:
        raise ValueError("Alpha ACP and independent Codex lanes required")
    return validated


def main() -> None:
    """Validate owner evidence and publish existing canonical attestations as the bot."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("local review ingestion runs only in trusted Actions")
    run_id = os.environ["GITHUB_RUN_ID"]
    run = controller.json_object(controller.gh_json(["api", f"repos/{controller.REPO}/actions/runs/{run_id}"])) or {}
    owner = controller.REPO.split("/")[0]
    if (run.get("event") != "workflow_dispatch" or run.get("head_branch") != "main"
            or run.get("actor", {}).get("login") != owner
            or run.get("path") != ".github/workflows/factory-local-review.yml"):
        raise RuntimeError("owner-dispatched trusted-main local-review workflow required")
    payload = json.loads(os.environ["LOCAL_REVIEW_EVIDENCE"])
    pr_number = payload["pr"]
    head = payload["head"]
    if not isinstance(pr_number, int) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("PR number and exact head required")
    pr = controller.pr_json(pr_number)
    if pr.get("headRefOid") != head or pr.get("state") != "OPEN" or pr.get("isDraft"):
        raise RuntimeError("PR moved, closed or draft")
    labels = {label["name"] for label in pr.get("labels", [])}
    if any(re.fullmatch(r"factory:[0-9]+", label) for label in labels):
        raise RuntimeError("another numbered factory owns the PR")
    provenance = controller.reconcile_provenance(pr_number=pr_number, expected_head=head)
    if provenance.get("status") not in {"attested", "already-attested"}:
        raise RuntimeError("exact-head authorship unavailable")
    comments = controller.review_comment_bodies(pr_number)
    contributors, _ = controller.head_contributor_provenance(comments, pr=pr_number, head=head)
    declared = payload.get("contributors")
    if not isinstance(declared, list) or not declared or not all(isinstance(x, str) for x in declared):
        raise ValueError("complete local contributor identities required")
    contributors.update(declared)
    lanes = validate_lanes(payload, head, contributors)
    issue, non_closing = controller.linked_issue_mode_for_pr(pr_number, str(pr.get("headRefName") or ""))
    if issue != payload.get("issue"):
        raise ValueError("linked issue mismatch")
    body = controller.target_json(issue)["body"]
    changed = controller.run_gh(["pr", "diff", str(pr_number), "--repo", controller.REPO, "--name-only"]).stdout.splitlines()
    errors = controller.issue_acceptance.validate(payload.get("acceptance"), issue, head, body, changed, non_closing=non_closing)
    if errors:
        raise ValueError("invalid original reviewer acceptance report: " + "; ".join(errors))
    delivery = controller.implementation_delivery_gate(pr_number, head, body)
    if delivery["decision"] != "pass":
        raise RuntimeError("implementation delivery gate: " + delivery["reason"])
    author = policy.current_head_author_identity(controller.model_comment_bodies(pr_number), pr=pr_number, head=head)
    if author is None:
        raise RuntimeError("controller author model unavailable")
    if controller.pr_json(pr_number).get("headRefOid") != head:
        raise RuntimeError("PR moved while validating evidence")
    for lane in lanes:
        marker = policy.review_marker(pr=pr_number, head=head, reviewer=lane["identity"], producer=None, verdict="approve")
        controller.run_gh(["issue", "comment", str(pr_number), "--repo", controller.REPO, "--body", marker + "\nActual local review: " + lane["identity"] + "\n" + controller.redact_review_text(lane["report"])[:7000]])
        if policy.normalize_model_family(lane["model"]) != author[0]:
            marker = policy.agent_model_review_marker(pr=pr_number, head=head, author_model=author[0], reviewer_model=lane["model"], author_agent=author[1], reviewer_agent=lane["identity"])
            controller.run_gh(["issue", "comment", str(pr_number), "--repo", controller.REPO, "--body", marker])
    controller.run_gh(["issue", "comment", str(pr_number), "--repo", controller.REPO, "--body", controller.issue_acceptance.marker(issue, head, body)])
    controller.replace_factory_labels(pr_number, "factory:unowned", "factory:ci")
    print(json.dumps({"pr": pr_number, "head": head, "status": "attested"}))


if __name__ == "__main__":
    main()
