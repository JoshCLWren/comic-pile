"""Regression coverage for demand-driven completion drain selection."""
from __future__ import annotations

from pathlib import Path
import sys
import importlib.util

if str(Path(__file__).resolve().parents[1] / ".github" / "scripts") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "scripts"))

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
    assert set(selected) == {str(worker) for worker in range(6, 13)}


def test_selector_respects_explicit_target_override():
    controller = full.load_controller()
    full.configure_demand_selection(controller, target=12)

    workers = [str(worker) for worker in range(6, 26)]
    health = dict.fromkeys(workers, ("success", 0))
    selected = controller.select_completion_workers(
        workers,
        review_backlog=3,
        health=health,
        now_epoch=1,
    )
    assert set(selected) == {str(worker) for worker in range(6, 18)}


def test_raw_demand_is_not_erased_by_legacy_review_backpressure_threshold():
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
