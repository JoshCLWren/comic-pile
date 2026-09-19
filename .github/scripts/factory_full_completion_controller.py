#!/usr/bin/env python3
"""Plan completion workers from current demand and idle fleet capacity."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

from factory_capacity_policy import (
    FleetDemand,
    apply_omniroute_free_entry_cap,
    completion_worker_target,
)


def load_controller():
    """Load the completion scheduling helpers without granting assignment authority."""
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
        if (linked := policy.linked_issue_from_pr(pr)) is not None
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


def current_demand(
    controller,
    *,
    now_epoch: int | None = None,
) -> tuple[FleetDemand, dict[str, object]]:
    """Measure work demand against idle, evidence-backed executable capacity."""
    work_controller = controller.load_controller()
    policy = controller.load_policy()
    issues = work_controller.list_issues()
    prs = work_controller.list_prs()
    completion, production = raw_work_demand(policy, issues, prs)

    now_epoch = int(time.time()) if now_epoch is None else now_epoch
    manifest = Path(__file__).resolve().parents[1] / "free-model-factories.tsv"
    candidates = controller.load_manifest_candidates(manifest)
    owned = controller.owned_worker_ids([*issues, *prs])
    try:
        comments = controller.registry_comments()
        health = controller.latest_worker_health(
            comments,
            trusted=policy.comment_is_trusted,
        )
    except RuntimeError as exc:
        print(
            f"[factory-completion] capacity evidence unavailable; failing closed: {exc}",
            file=sys.stderr,
        )
        health = {}
    capacity = controller.capacity_report(candidates, health, now_epoch=now_epoch)
    idle = sum(
        candidate["worker"] not in owned
        and controller.worker_is_executable(
            candidate["worker"],
            health,
            now_epoch=now_epoch,
        )
        for candidate in candidates
    )
    demand = apply_omniroute_free_entry_cap(
        FleetDemand(completion=completion, production=production, idle_workers=idle),
        work_controller.in_flight_omniroute_free_entries(),
    )
    return demand, capacity


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
        del review_backlog
        owned_workers = owned_workers or set()
        health = health or {}
        now_epoch = int(time.time()) if now_epoch is None else now_epoch

        healthy: list[str] = []
        degraded: list[str] = []
        for worker in workers:
            if worker in owned_workers:
                continue
            state = controller.worker_health_state(worker, health, now_epoch=now_epoch)
            if state == "healthy":
                healthy.append(worker)
            elif state == "degraded":
                degraded.append(worker)

        healthy.sort(key=int)
        degraded.sort(key=int)
        return (healthy + degraded)[:target]

    controller.select_completion_workers = select_workers


def plan_completion_workers(
    controller,
    *,
    target: int,
    now_epoch: int | None = None,
) -> list[str]:
    """Return the health-aware idle worker batch without mutating any lease."""
    if target <= 0:
        return []

    now_epoch = int(time.time()) if now_epoch is None else now_epoch
    work_controller = controller.load_controller()
    policy = controller.load_policy()
    issues = work_controller.list_issues()
    prs = work_controller.list_prs()
    manifest = Path(__file__).resolve().parents[1] / "free-model-factories.tsv"
    candidates = controller.load_manifest_candidates(manifest)
    workers = [candidate["worker"] for candidate in candidates]
    owned = controller.owned_worker_ids([*issues, *prs])

    try:
        comments = controller.registry_comments()
        health = controller.latest_worker_health(
            comments,
            trusted=policy.comment_is_trusted,
            candidates=candidates,
            now_epoch=now_epoch,
        )
    except RuntimeError as exc:
        print(
            f"[factory-completion] heartbeat health unavailable; failing closed: {exc}",
            file=sys.stderr,
        )
        return []

    configure_demand_selection(controller, target=target)
    return controller.select_completion_workers(
        workers,
        review_backlog=policy.factory_review_backlog_count(prs),
        owned_workers=owned,
        health=health,
        now_epoch=now_epoch,
    )


def main() -> int:
    """Emit a read-only completion-capacity plan for the central dispatcher."""
    controller = load_controller()
    now_epoch = int(time.time())
    demand, capacity = current_demand(controller, now_epoch=now_epoch)
    target = completion_worker_target(demand)
    selected = plan_completion_workers(
        controller,
        target=target,
        now_epoch=now_epoch,
    )
    result: dict[str, object] = {
        "completion_demand": demand.completion,
        "production_demand": demand.production,
        "idle_workers": demand.idle_workers,
        "completion_share": demand.completion_share,
        "completion_target": target,
        "selected_workers": selected,
        "assignment_authority": "Fixed Model Factory Dispatcher",
        **capacity,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
