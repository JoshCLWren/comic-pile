#!/usr/bin/env python3
"""Run the completion drain at full healthy-fleet capacity under severe backlog."""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path


def load_controller():
    path = Path(__file__).resolve().with_name("factory_completion_controller.py")
    spec = importlib.util.spec_from_file_location("factory_completion_controller_full", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load factory_completion_controller.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
