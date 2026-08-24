#!/usr/bin/env python3
"""Run the completion drain at full healthy-fleet capacity under severe backlog."""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

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

    # Severe backlog means the completion lane is the fleet's primary job.
    # Remove the artificial 12-worker ceiling and let the existing health,
    # ownership, and review-capacity filters determine safe concurrency.
    controller.HIGH_DRAIN_BATCH = 10_000

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
