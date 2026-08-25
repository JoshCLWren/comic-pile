"""Regression coverage for demand-driven completion drain selection."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "scripts"
    / "factory_full_completion_controller.py"
)
SPEC = importlib.util.spec_from_file_location("factory_full_completion_controller", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
full = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = full
SPEC.loader.exec_module(full)


def test_selector_uses_calculated_target_without_backlog_thresholds():
    controller = full.load_controller()
    full.configure_demand_selection(controller, target=7)

    workers = [str(worker) for worker in range(6, 26)]
    selected = controller.select_completion_workers(
        workers,
        review_backlog=3,
        now_epoch=1,
    )

    assert selected == workers[:7]
    assert controller.completion_batch_size(3) == 7


def test_raw_demand_is_not_erased_by_legacy_review_backpressure_threshold():
    controller = full.load_controller()
    policy = controller.load_policy()
    prs = [
        {
            "number": 100 + index,
            "state": "OPEN",
            "isDraft": False,
            "headRefName": f"factory/6-{2000 + index}-review",
            "labels": ["factory:review", "factory:unowned"],
            "createdAt": "2026-08-24T00:00:00Z",
        }
        for index in range(policy.FACTORY_REVIEW_BACKLOG_LIMIT)
    ]
    issue = {
        "number": 9999,
        "state": "OPEN",
        "labels": ["factory:unowned"],
        "createdAt": "2026-08-24T00:00:00Z",
    }

    legacy = policy.build_candidates([issue], prs, no_diff_attempts_by_issue={})
    assert not any(candidate.kind == "issue" for candidate in legacy)
    assert full.raw_work_demand(policy, [issue], prs) == (
        policy.FACTORY_REVIEW_BACKLOG_LIMIT,
        1,
    )


def test_transient_cooldowns_are_fallback_capacity_but_model_missing_is_not():
    controller = full.load_controller()
    full.configure_demand_selection(controller, target=4)
    now = controller.parse_time("2026-08-24T17:00:00Z")
    assert now is not None

    workers = ["6", "7", "8", "9", "10", "11"]
    health = {
        "6": ("failure", now - 60),
        "8": ("RATE LIMITED", now - 60),
        "10": ("MODEL MISSING", now - 60),
    }

    selected = controller.select_completion_workers(
        workers,
        review_backlog=35,
        owned_workers={"7"},
        health=health,
        now_epoch=now,
    )

    assert "7" not in selected
    assert "10" not in selected
    assert selected == ["9", "11", "6", "8"]
