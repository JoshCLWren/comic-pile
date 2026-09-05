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
    health = dict.fromkeys(workers, ("success", 0))
    selected = controller.select_completion_workers(
        workers,
        review_backlog=3,
        health=health,
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


def test_raw_demand_counts_human_closing_pr_as_suppressing_issue():
    """Production demand respects a human `local/*` PR that closes an issue."""
    controller = full.load_controller()
    policy = controller.load_policy()
    issue = {
        "number": 2127,
        "state": "OPEN",
        "labels": ["factory:unowned"],
        "createdAt": "2026-08-24T00:00:00Z",
    }
    human = {
        "number": 2161,
        "state": "OPEN",
        "isDraft": False,
        "headRefName": "local/2127-cbl-commit",
        "body": "Closes #2127",
        "labels": ["factory", "factory:unowned"],
        "createdAt": "2026-08-24T00:00:00Z",
    }

    assert policy._linked_issue_from_pr(human) == 2127
    assert policy.pr_suppresses_issue_candidate(human, {})
    assert full.raw_work_demand(policy, [issue], [human]) == (0, 0)


def test_only_healthy_or_degraded_workers_count_as_executable_capacity():
    controller = full.load_controller()
    full.configure_demand_selection(controller, target=4)
    now = controller.parse_time("2026-08-24T17:00:00Z")
    assert now is not None

    workers = ["6", "7", "8", "9", "10", "11"]
    health = {
        "6": ("failure", now - 60),
        "8": ("RATE LIMITED", now - 60),
        "9": ("success", now - 60),
        "10": ("MODEL MISSING", now - 60),
        "11": ("provider_unavailable", now - 3600),
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
    assert "6" not in selected
    assert "8" not in selected
    assert selected == ["9", "11"]
