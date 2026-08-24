#!/usr/bin/env python3
"""Allocate completion workers from current demand and idle fleet capacity."""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from factory_capacity_policy import FleetDemand, completion_worker_target

TELEMETRY_MARKER = "<!-- factory-completion-funnel:v1 -->"
TELEMETRY_ISSUE = "1093"


def load_controller():
    path = Path(__file__).resolve().with_name("factory_completion_controller.py")
    spec = importlib.util.spec_from_file_location("factory_completion_controller_full", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load factory_completion_controller.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def raw_work_demand(policy, issues, prs) -> tuple[int, int]:
    """Count independent completion and production demand before capacity policy.

    The legacy candidate builder intentionally suppresses fresh issue intake once
    completion backlog crosses a fixed threshold. That is an execution guard,
    not a measurement of demand. Feeding it into the ratio allocator would make
    production demand disappear at the old threshold and recreate the magic
    number indirectly. Measure structurally eligible work here instead.
    """
    issue_map = {int(issue["number"]): issue for issue in issues}
    completion = sum(policy.pr_is_static_candidate(pr, issue_map) for pr in prs)

    suppressing_pr_issues = {
        linked
        for pr in prs
        if (linked := policy.linked_issue_from_branch(pr.get("headRefName"))) is not None
        and policy.pr_suppresses_issue_candidate(pr, issue_map)
    }
    production = sum(
        policy.issue_is_static_candidate(
            issue,
            suppressing_pr_issues,
            no_diff_attempts=0,
        )
        for issue in issues
    )
    return completion, production


def current_demand(controller) -> FleetDemand:
    """Measure independent work demand against idle configured capacity."""
    work_controller = controller.load_controller()
    policy = controller.load_policy()
    issues = work_controller.list_issues()
    prs = work_controller.list_prs()
    completion, production = raw_work_demand(policy, issues, prs)

    manifest = Path(__file__).resolve().parents[1] / "free-model-factories.tsv"
    workers = controller.load_manifest_workers(manifest)
    owned = controller.owned_worker_ids([*issues, *prs])
    idle = sum(worker not in owned for worker in workers)
    return FleetDemand(completion=completion, production=production, idle_workers=idle)


def configure_demand_selection(controller, *, target: int) -> None:
    """Select completion workers from calculated demand instead of threshold tiers."""
    controller.REVIEW_BACKLOG_LIMIT = 1
    controller.completion_batch_size = lambda backlog: target if backlog > 0 else 0

    def select_workers(
        workers,
        *,
        review_backlog,
        owned_workers=None,
        health=None,
        now_epoch=None,
    ):
        owned_workers = owned_workers or set()
        health = health or {}
        now_epoch = int(time.time()) if now_epoch is None else now_epoch

        healthy: list[str] = []
        transiently_cooling: list[str] = []
        for worker in workers:
            if worker in owned_workers:
                continue
            status = health.get(worker)
            if status is not None:
                outcome, updated = status
                normalized = (outcome or "").strip().casefold()
                cooldown = controller.cooldown_seconds(outcome)
                still_cooling = cooldown > 0 and now_epoch < updated + cooldown
                if still_cooling and "model missing" in normalized:
                    continue
                if still_cooling:
                    transiently_cooling.append(worker)
                    continue
            healthy.append(worker)

        healthy.sort(key=int)
        transiently_cooling.sort(key=int)
        return (healthy + transiently_cooling)[:target]

    controller.select_completion_workers = select_workers


def persist_funnel_telemetry(controller, result: dict[str, object]) -> None:
    """Persist demand, allocation, and claim results for operational verification."""
    selected = list(result.get("selected_workers") or [])
    assignments = list(result.get("assignments") or [])
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    body = "\n".join(
        [
            TELEMETRY_MARKER,
            "## Factory completion funnel",
            f"Completion demand: {result.get('completion_demand', 0)}",
            f"Production demand: {result.get('production_demand', 0)}",
            f"Idle configured workers: {result.get('idle_workers', 0)}",
            f"Completion share: {float(result.get('completion_share', 0.0)):.3f}",
            f"Completion target: {result.get('completion_target', 0)}",
            f"Workers selected: {len(selected)}",
            f"PR claims succeeded: {len(assignments)}",
            "Selected worker IDs: " + (", ".join(map(str, selected)) if selected else "none"),
            "Assignments: "
            + (
                ", ".join(
                    f"Factory {item.get('worker')} → PR #{item.get('number')}"
                    for item in assignments
                    if isinstance(item, dict)
                )
                if assignments
                else "none"
            ),
            f"Updated: {now}",
        ]
    )
    try:
        comments = controller.flatten_pages(
            controller.gh_json(
                [
                    "api",
                    "--paginate",
                    "--slurp",
                    f"repos/{controller.REPO}/issues/{TELEMETRY_ISSUE}/comments?per_page=100",
                ]
            )
        )
        existing = next(
            (
                str(comment.get("id"))
                for comment in comments
                if TELEMETRY_MARKER in str(comment.get("body") or "")
            ),
            "",
        )
        method = "PATCH" if existing else "POST"
        endpoint = (
            f"repos/{controller.REPO}/issues/comments/{existing}"
            if existing
            else f"repos/{controller.REPO}/issues/{TELEMETRY_ISSUE}/comments"
        )
        controller.run_gh(["api", "--method", method, endpoint, "-f", f"body={body}"])
    except RuntimeError as exc:
        print(f"[factory-completion] unable to persist funnel telemetry: {exc}", file=sys.stderr)


def main() -> int:
    controller = load_controller()
    demand = current_demand(controller)
    target = completion_worker_target(demand)
    configure_demand_selection(controller, target=target)

    original_load_work_controller = controller.load_controller

    def load_pr_only_work_controller():
        work_controller = original_load_work_controller()
        original_assign_candidate = work_controller.assign_candidate

        def assign_completion_candidate(candidate, worker):
            if candidate.kind == "pr" and candidate.linked_issue is not None:
                candidate = dataclasses.replace(candidate, linked_issue=None)
            return original_assign_candidate(candidate, worker)

        work_controller.assign_candidate = assign_completion_candidate
        return work_controller

    controller.load_controller = load_pr_only_work_controller

    result = controller.assign_completion_batch()
    result.update(
        {
            "completion_demand": demand.completion,
            "production_demand": demand.production,
            "idle_workers": demand.idle_workers,
            "completion_share": demand.completion_share,
            "completion_target": target,
        }
    )
    persist_funnel_telemetry(controller, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
