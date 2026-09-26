"""Regression coverage for demand-driven completion drain selection."""
from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

scripts_dir = Path(__file__).resolve().parents[1] / ".github" / "scripts"
sys.path.insert(0, str(scripts_dir))

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


@contextmanager
def stubbed_work_controller(controller):
    """Replace the gh-backed work controller with an offline stub.

    signal_dispatch only needs owned-worker lookup and reconciliation
    hooks from the work controller; stubbing keeps these regression tests
    hermetic (no gh auth or network required).
    """
    work = MagicMock()
    work.list_issues.return_value = []
    work.list_prs.return_value = []
    work.reconcile_stale_leases.return_value = []
    work.reconcile_contradictory_labels.return_value = []
    original = controller.load_controller
    controller.load_controller = lambda: work
    try:
        yield work
    finally:
        controller.load_controller = original


def test_signal_dispatch_returns_no_assignments():
    controller = full.load_controller()
    demand = full.FleetDemand(
        completion=0, production=0, idle_workers=0
    )
    capacity = {"enabled": 0, "in_flight": 0, "cap": 12, "remaining": 12}
    with stubbed_work_controller(controller):
        result = full.signal_dispatch(controller, demand, capacity)
    assert result["assignments"] == []
    assert result["signal"] in ("explicit-worker", "roster")
    # Capacity refill derives its executable worker set from the canonical
    # capacity report, so it must be consistent with demand measurement.
    assert result["idle_executable_workers"] >= 0


def test_signal_dispatch_includes_demand_data():
    controller = full.load_controller()
    demand = full.FleetDemand(
        completion=1, production=2, idle_workers=3
    )
    capacity = {"enabled": 0, "in_flight": 0, "cap": 12, "remaining": 12}
    with stubbed_work_controller(controller):
        result = full.signal_dispatch(controller, demand, capacity)
    assert "completion_demand" in result
    assert "production_demand" in result
    assert "completion_share" in result
    assert "completion_target" in result
    assert "capacity" in result


def test_signal_dispatch_performs_reconciliation():
    controller = full.load_controller()
    demand = full.FleetDemand(
        completion=0, production=0, idle_workers=0
    )
    capacity = {"enabled": 0, "in_flight": 0, "cap": 12, "remaining": 12}
    with stubbed_work_controller(controller) as work:
        result = full.signal_dispatch(controller, demand, capacity)
    assert "signal" in result
    assert "assignments" in result
    assert result["assignments"] == []
    work.reconcile_stale_leases.assert_called_once()
    work.reconcile_contradictory_labels.assert_called_once()


def test_signal_dispatch_omits_direct_assignment():
    controller = full.load_controller()
    demand = full.FleetDemand(
        completion=0, production=0, idle_workers=0
    )
    capacity = {"enabled": 0, "in_flight": 0, "cap": 12, "remaining": 12}
    with stubbed_work_controller(controller):
        result = full.signal_dispatch(controller, demand, capacity)
    assert result["assignments"] == []


def test_main_does_not_assign_directly():
    from unittest.mock import patch

    with patch.object(full, "current_demand") as mock_demand, \
         patch.object(full, "persist_funnel_telemetry") as mock_persist, \
         patch.object(full, "signal_dispatch") as mock_signal:
        mock_demand.return_value = (
            full.FleetDemand(completion=0, production=0, idle_workers=0),
            {"enabled": 0, "in_flight": 0, "cap": 12, "remaining": 12},
        )
        mock_signal.return_value = {"signal": "roster", "assignments": []}
        full.main()
        mock_signal.assert_called_once()
        mock_persist.assert_called_once()


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


def test_current_demand_caps_idle_workers_to_remaining_omniroute_slots():
    from unittest.mock import patch

    with patch.dict("os.environ", {"FACTORY_OMNIROUTE_ENABLED": "on"}):
        _assert_current_demand_caps()


def test_current_demand_uses_multi_provider_budget_when_omniroute_dark():
    from unittest.mock import patch

    env = dict(__import__("os").environ)
    env.pop("FACTORY_OMNIROUTE_ENABLED", None)
    with patch.dict("os.environ", env, clear=True):
        _assert_current_demand_multi_provider()


def _assert_current_demand_caps():
    class FakeWork:
        def list_issues(self):
            return []

        def list_prs(self):
            return []

        def in_flight_omniroute_free_entries(self):
            return 2

    class FakePolicy:
        def comment_is_trusted(self, comment):
            return True

        def pr_is_static_candidate(self, pr, issue_map):
            return False

        def linked_issue_from_branch(self, name):
            return None

        def linked_issue_from_pr(self, pr):
            return None

        def pr_suppresses_issue_candidate(self, pr, issue_map):
            return False

        def issue_is_static_candidate(self, issue, suppressing, no_diff_attempts=0):
            return False

    class FakeCompletion:
        def load_controller(self):
            return FakeWork()

        def load_policy(self):
            return FakePolicy()

        def load_manifest_candidates(self, manifest):
            return [{"worker": str(worker)} for worker in range(6, 16)]

        def owned_worker_ids(self, items):
            return set()

        def registry_comments(self):
            return []

        def latest_worker_health(self, comments, trusted):
            return {}

        def capacity_report(self, candidates, health, now_epoch):
            return {"executable_slot_capacity": 10}

        def worker_is_executable(self, worker, health, now_epoch):
            return True

    measured, capacity = full.current_demand(FakeCompletion(), now_epoch=1)
    assert measured.idle_workers == 1
    assert measured.completion == 0
    assert measured.production == 0
    assert full.completion_worker_target(measured) == 0
    assert capacity["executable_slot_capacity"] == 10


def _assert_current_demand_multi_provider():
    class FakeWork:
        def list_issues(self):
            return []

        def list_prs(self):
            return []

        def in_flight_omniroute_free_entries(self):
            return 2

    class FakePolicy:
        def comment_is_trusted(self, comment):
            return True

        def pr_is_static_candidate(self, pr, issue_map):
            return False

        def linked_issue_from_branch(self, name):
            return None

        def linked_issue_from_pr(self, pr):
            return None

        def pr_suppresses_issue_candidate(self, pr, issue_map):
            return False

        def issue_is_static_candidate(self, issue, suppressing, no_diff_attempts=0):
            return False

    class FakeCompletion:
        def load_controller(self):
            return FakeWork()

        def load_policy(self):
            return FakePolicy()

        def load_manifest_candidates(self, manifest):
            return [{"worker": str(worker)} for worker in range(6, 16)]

        def owned_worker_ids(self, items):
            return set()

        def registry_comments(self):
            return []

        def latest_worker_health(self, comments, trusted):
            return {}

        def capacity_report(self, candidates, health, now_epoch):
            return {"executable_slot_capacity": 10}

        def worker_is_executable(self, worker, health, now_epoch):
            return True

    measured, capacity = full.current_demand(FakeCompletion(), now_epoch=1)
    assert measured.idle_workers == 10
    assert measured.completion == 0
    assert measured.production == 0
    assert full.completion_worker_target(measured) == 0
    assert capacity["executable_slot_capacity"] == 10