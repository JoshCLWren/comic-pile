#!/usr/bin/env python3
"""Run the completion drain at full healthy-fleet capacity under severe backlog."""
from __future__ import annotations

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
    result = controller.assign_completion_batch()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
