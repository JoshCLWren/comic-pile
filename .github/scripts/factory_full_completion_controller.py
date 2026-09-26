#!/usr/bin/env python3
"""Allocate completion workers from current demand and idle fleet capacity."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from factory_capacity_policy import (
    FleetDemand,
    apply_omniroute_free_entry_cap,
    completion_worker_target,
)

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


def current_demand(controller, *, now_epoch: int | None = None) -> tuple[FleetDemand, dict[str, object]]:
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
            f"Idle executable workers: {result.get('idle_workers', 0)}",
            f"Executable slot capacity: {result.get('executable_slot_capacity', 0)}",
            "Slot health: "
            + json.dumps(result.get("slot_health_counts", {}), sort_keys=True),
            f"Executable provider/model candidates: "
            f"{result.get('executable_candidate_count', 0)}",
            "Candidate health: "
            + json.dumps(result.get("candidate_health_counts", {}), sort_keys=True),
            "Executable provider/models: "
            + (
                ", ".join(
                    f"{item.get('provider')}/{item.get('model')}"
                    for item in result.get("executable_provider_models", [])
                    if isinstance(item, dict)
                )
                or "none"
            ),
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


def signal_dispatch(controller, demand: FleetDemand, capacity: dict[str, object]) -> dict[str, object]:
    """Signal the dispatcher with demand and capacity without assigning or launching.

    Capacity refill may perform recovery/reconciliation but does not
    directly assign workers or launch entries. Healthy one-for-one
    refill signals an explicit-worker dispatcher mode that cannot create
    a self-perpetuating roster chain. Broad bootstrap signals roster mode.

    The executable worker set is derived from the capacity report passed in
    by current_demand() so it stays consistent with the measured idle_workers
    count instead of re-deriving health from an empty snapshot.
    """
    target = completion_worker_target(demand)
    now_epoch = int(time.time())
    try:
        work_controller = controller.load_controller()
        owned = controller.owned_worker_ids(
            work_controller.list_issues() + work_controller.list_prs()
        )

        # Perform recovery/reconciliation without assignment
        work_controller.reconcile_stale_leases(now_epoch=now_epoch)
        work_controller.reconcile_contradictory_labels()
    except RuntimeError as exc:
        # Signal-only path must stay fail-open: when GitHub evidence is
        # unavailable (e.g. no gh auth in CI), still wake the dispatcher
        # with demand/capacity data instead of crashing.
        print(
            f"[factory-completion] signal evidence unavailable; "
            f"continuing without reconciliation: {exc}",
            file=sys.stderr,
        )
        owned = set()

    executable_candidates = list(capacity.get("executable_candidates") or [])
    eligible = [
        str(candidate["worker"])
        for candidate in executable_candidates
        if str(candidate["worker"]) not in owned
    ]
    eligible.sort(key=int)

    # Determine mode: explicit-worker for one-for-one, roster for broad bootstrap
    mode = "explicit-worker" if 0 < target <= 1 else "roster"

    return {
        "signal": mode,
        "selected_workers": eligible[:target] if target > 0 else [],
        "completion_demand": demand.completion,
        "production_demand": demand.production,
        "idle_workers": demand.idle_workers,
        "completion_share": demand.completion_share,
        "completion_target": target,
        "idle_executable_workers": len(eligible),
        "capacity": capacity,
        "assignments": [],
    }


def main() -> int:
    controller = load_controller()
    demand, capacity = current_demand(controller)
    result = signal_dispatch(controller, demand, capacity)
    persist_funnel_telemetry(controller, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
