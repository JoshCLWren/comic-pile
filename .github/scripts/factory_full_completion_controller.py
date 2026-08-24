#!/usr/bin/env python3
"""Run the completion drain at full fleet capacity whenever backlog is saturated."""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TELEMETRY_MARKER = "<!-- factory-completion-funnel:v1 -->"
TELEMETRY_ISSUE = "1093"
FULL_FLEET_BATCH = 10_000


def load_controller():
    path = Path(__file__).resolve().with_name("factory_completion_controller.py")
    spec = importlib.util.spec_from_file_location("factory_completion_controller_full", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load factory_completion_controller.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def configure_work_conserving_selection(controller) -> None:
    """Use every idle configured worker before leaving completion work waiting."""
    # The previous wrapper only lifted HIGH_DRAIN_BATCH, so a backlog that fell
    # from 50 to 49 silently dropped back to an eight-worker ceiling. Saturated
    # completion work should instead consume all available fleet capacity.
    controller.NORMAL_DRAIN_BATCH = FULL_FLEET_BATCH
    controller.HIGH_DRAIN_BATCH = FULL_FLEET_BATCH

    def select_all_idle_workers(
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

        healthy = []
        transiently_cooling = []
        for worker in workers:
            if worker in owned_workers:
                continue
            status = health.get(worker)
            if status is not None:
                outcome, updated = status
                normalized = (outcome or "").strip().casefold()
                cooldown = controller.cooldown_seconds(outcome)
                still_cooling = cooldown > 0 and now_epoch < updated + cooldown
                # A configured model that does not exist cannot make progress.
                if still_cooling and "model missing" in normalized:
                    continue
                if still_cooling:
                    transiently_cooling.append(worker)
                    continue
            healthy.append(worker)

        def priority(worker):
            return (
                not controller.review_capacity_worker(
                    worker, review_backlog=review_backlog
                ),
                int(worker),
            )

        healthy.sort(key=priority)
        transiently_cooling.sort(key=priority)
        limit = controller.completion_batch_size(review_backlog)
        if limit == 0:
            return []
        return (healthy + transiently_cooling)[:limit]

    controller.select_completion_workers = select_all_idle_workers


def persist_funnel_telemetry(controller, result: dict[str, object]) -> None:
    """Persist one durable snapshot so scheduler and selection failures are visible."""
    backlog = int(result.get("backlog") or 0)
    selected = list(result.get("selected_workers") or [])
    assignments = list(result.get("assignments") or [])
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    body = "\n".join(
        [
            TELEMETRY_MARKER,
            "## Factory completion funnel",
            f"Backlog: {backlog}",
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
        if existing:
            controller.run_gh(
                [
                    "api",
                    "--method",
                    "PATCH",
                    f"repos/{controller.REPO}/issues/comments/{existing}",
                    "-f",
                    f"body={body}",
                ]
            )
        else:
            controller.run_gh(
                [
                    "api",
                    "--method",
                    "POST",
                    f"repos/{controller.REPO}/issues/{TELEMETRY_ISSUE}/comments",
                    "-f",
                    f"body={body}",
                ]
            )
    except RuntimeError as exc:
        print(f"[factory-completion] unable to persist funnel telemetry: {exc}", file=sys.stderr)


def main() -> int:
    controller = load_controller()
    configure_work_conserving_selection(controller)

    # A semantic reviewer needs a lease on the PR, not on the implementation
    # issue that originally produced it. Reusing the implementation claim shape
    # made one review consume two visible targets and distorted WIP telemetry.
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
    persist_funnel_telemetry(controller, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
