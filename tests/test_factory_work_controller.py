"""Regression coverage for centralized factory assignment and leases."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


CONTROLLER_PATH = Path(".github/scripts/factory-work-controller.py")


def load_controller():
    spec = importlib.util.spec_from_file_location("factory_work_controller", CONTROLLER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def issue(number: int, *labels: str, created: str = "2026-08-16T12:00:00Z"):
    return {
        "number": number,
        "title": f"Issue {number}",
        "labels": [{"name": label} for label in labels],
        "createdAt": created,
    }


def pr(
    number: int,
    branch: str,
    *labels: str,
    created: str = "2026-08-16T12:00:00Z",
):
    return {
        "number": number,
        "title": f"PR {number}",
        "labels": [{"name": label} for label in labels],
        "headRefName": branch,
        "createdAt": created,
        "isDraft": False,
    }


def test_user_report_beats_ordinary_product_and_e2e() -> None:
    controller = load_controller()
    candidates = controller.build_candidates(
        [
            issue(101, "bug", "e2e-discovered", "factory:unowned"),
            issue(102, "enhancement", "factory:unowned"),
            issue(103, "bug", "user-reported", "factory:unowned"),
        ],
        [],
    )

    assert [(candidate.number, candidate.lane) for candidate in candidates] == [
        (103, 1),
        (102, 3),
        (101, 4),
    ]


def test_ordinary_product_beats_e2e_even_when_e2e_is_newer() -> None:
    controller = load_controller()
    candidates = controller.build_candidates(
        [
            issue(
                201,
                "bug",
                "e2e-discovered",
                "factory:unowned",
                created="2026-08-16T15:00:00Z",
            ),
            issue(
                202,
                "enhancement",
                "factory:unowned",
                created="2026-08-01T15:00:00Z",
            ),
        ],
        [],
    )

    assert [candidate.number for candidate in candidates] == [202, 201]


def test_e2e_is_selected_when_higher_lanes_are_empty() -> None:
    controller = load_controller()
    candidates = controller.build_candidates(
        [issue(301, "bug", "e2e-discovered", "factory:unowned")],
        [],
    )

    assert len(candidates) == 1
    assert candidates[0].number == 301
    assert candidates[0].lane == 4


def test_user_bug_pr_repair_inherits_priority_without_worker_affinity() -> None:
    controller = load_controller()
    issues = [
        issue(401, "bug", "user-reported", "factory:unowned"),
        issue(402, "enhancement", "factory:unowned"),
    ]
    prs = [
        pr(
            1401,
            "factory/27-401-fix",
            "factory",
            "factory:unowned",
            "factory:changes-requested",
        )
    ]

    candidates = controller.build_candidates(issues, prs)

    # The open PR suppresses duplicate issue implementation and is ranked by
    # the linked user-report provenance, not by the worker number in its branch.
    assert [(candidate.kind, candidate.number, candidate.lane) for candidate in candidates] == [
        ("pr", 1401, 2),
        ("issue", 402, 3),
    ]


def test_ready_pr_is_reserved_for_merge_controller() -> None:
    controller = load_controller()
    candidates = controller.build_candidates(
        [],
        [
            pr(
                1501,
                "factory/13-501-opencode-free",
                "factory",
                "factory:unowned",
                "factory:ready",
            )
        ],
    )

    assert candidates == []


def test_stale_fixed_lease_releases_but_live_worker_is_not_stolen() -> None:
    controller = load_controller()

    assert controller.lease_is_stale(
        "factory:13",
        active_fixed_workers=set(),
        latest_activity_epoch=None,
        now_epoch=10_000,
    )
    assert not controller.lease_is_stale(
        "factory:13",
        active_fixed_workers={13},
        latest_activity_epoch=None,
        now_epoch=10_000,
    )


def test_local_lease_requires_explicit_stale_activity_evidence() -> None:
    controller = load_controller()

    assert controller.lease_is_stale(
        "factory:local",
        active_fixed_workers=set(),
        latest_activity_epoch=1_000,
        now_epoch=10_000,
        local_ttl_seconds=8_100,
    )
    assert not controller.lease_is_stale(
        "factory:local",
        active_fixed_workers=set(),
        latest_activity_epoch=None,
        now_epoch=10_000,
        local_ttl_seconds=8_100,
    )


def test_one_dispatch_batch_plans_distinct_targets() -> None:
    controller = load_controller()
    candidates = [
        controller.Candidate("issue", 601, 1, 3, "2026-08-16T12:00:00Z"),
        controller.Candidate("issue", 602, 3, 2, "2026-08-16T11:00:00Z"),
    ]

    plan = controller.plan_distinct_assignments(candidates, ["13", "29"])

    assert plan["13"].number == 601
    assert plan["29"].number == 602


def test_active_worker_no_longer_performs_repo_wide_selection_or_merging() -> None:
    worker = Path(".github/scripts/free-model-factory-worker.sh").read_text(encoding="utf-8")

    assert "choose_existing_pr" not in worker
    assert "choose_ranked_issues" not in worker
    assert "claim_from_pool" not in worker
    assert "select_controller_assignment" in worker
    assert "exiting without repo-wide selection" in worker
    assert "handing it to the merge controller" in worker
    assert 'gh pr merge "$NUMBER"' not in worker


def test_dispatcher_serializes_assignment_and_survives_one_dispatch_failure() -> None:
    dispatcher = Path(".github/workflows/free-model-factory-dispatch.yml").read_text(
        encoding="utf-8"
    )

    assert "group: fixed-model-factory-dispatch" in dispatcher
    assert 'python3 "$controller" reconcile' in dispatcher
    assert 'assignment="$(python3 "$controller" assign --worker "$worker")"' in dispatcher
    assert "while (( attempt <= 3 ))" in dispatcher
    assert 'python3 "$controller" release --worker "$worker"' in dispatcher
    assert 'dispatch_assigned_worker "$worker" || dispatch_failures=' in dispatcher
    assert "later workers were still attempted" in dispatcher


def test_entry_run_name_exposes_queued_worker_identity() -> None:
    entry = Path(".github/workflows/free-model-factory-entry.yml").read_text(encoding="utf-8")

    assert "run-name: Factory ${{ inputs.worker }} · fixed-model entry" in entry
