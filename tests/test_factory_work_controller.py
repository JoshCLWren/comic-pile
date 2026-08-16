"""Regression coverage for centralized factory assignment and leases."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_PATH = REPO_ROOT / ".github/scripts/factory-work-controller.py"


@pytest.fixture(scope="module")
def controller() -> types.ModuleType:
    """Load the factory work controller once for this regression module."""
    spec = importlib.util.spec_from_file_location("factory_work_controller", CONTROLLER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def issue(
    number: int,
    *labels: str,
    created: str = "2026-08-16T12:00:00Z",
) -> dict[str, Any]:
    """Build a minimal issue payload for controller ranking tests."""
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
    draft: bool = False,
) -> dict[str, Any]:
    """Build a minimal pull-request payload for controller ranking tests."""
    return {
        "number": number,
        "title": f"PR {number}",
        "labels": [{"name": label} for label in labels],
        "headRefName": branch,
        "createdAt": created,
        "isDraft": draft,
    }


def test_user_report_beats_ordinary_product_and_e2e(controller: types.ModuleType) -> None:
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


def test_ordinary_product_beats_e2e_even_when_e2e_is_newer(
    controller: types.ModuleType,
) -> None:
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


def test_e2e_is_selected_when_higher_lanes_are_empty(controller: types.ModuleType) -> None:
    candidates = controller.build_candidates(
        [issue(301, "bug", "e2e-discovered", "factory:unowned")],
        [],
    )
    assert [(candidate.number, candidate.lane) for candidate in candidates] == [(301, 4)]


def test_equal_priority_items_preserve_established_newest_first_tie_break(
    controller: types.ModuleType,
) -> None:
    candidates = controller.build_candidates(
        [
            issue(
                310,
                "bug",
                "user-reported",
                "factory:unowned",
                created="2026-08-15T12:00:00Z",
            ),
            issue(
                311,
                "bug",
                "user-reported",
                "factory:unowned",
                created="2026-08-16T12:00:00Z",
            ),
        ],
        [],
    )
    assert [candidate.number for candidate in candidates] == [311, 310]


def test_user_bug_pr_repair_inherits_priority_without_worker_affinity(
    controller: types.ModuleType,
) -> None:
    candidates = controller.build_candidates(
        [
            issue(401, "bug", "user-reported", "factory:unowned"),
            issue(402, "enhancement", "factory:unowned"),
        ],
        [
            pr(
                1401,
                "factory/27-401-fix",
                "factory",
                "factory:unowned",
                "factory:changes-requested",
            )
        ],
    )
    assert [(candidate.kind, candidate.number, candidate.lane) for candidate in candidates] == [
        ("pr", 1401, 2),
        ("issue", 402, 3),
    ]


def test_controller_uses_only_canonical_worker_issue_branch_shape(
    controller: types.ModuleType,
) -> None:
    assert controller.linked_issue_from_branch("factory/27-401-repair") == 401
    assert controller.linked_issue_from_branch("factory/27-repair") is None
    assert controller.linked_issue_from_branch("factory/401-repair") is None


def test_draft_pr_does_not_make_linked_issue_disappear(controller: types.ModuleType) -> None:
    candidates = controller.build_candidates(
        [issue(411, "bug", "user-reported", "factory:unowned")],
        [
            pr(
                1411,
                "factory/27-411-fix",
                "factory",
                "factory:unowned",
                draft=True,
            )
        ],
    )
    assert [(candidate.kind, candidate.number) for candidate in candidates] == [
        ("issue", 411)
    ]


def test_blocked_pr_does_not_make_unblocked_linked_issue_disappear(
    controller: types.ModuleType,
) -> None:
    candidates = controller.build_candidates(
        [issue(412, "bug", "user-reported", "factory:unowned")],
        [
            pr(
                1412,
                "factory/27-412-fix",
                "factory",
                "factory:unowned",
                "factory:blocked",
            )
        ],
    )
    assert [(candidate.kind, candidate.number) for candidate in candidates] == [
        ("issue", 412)
    ]


def test_ready_pr_is_reserved_for_merge_controller_and_suppresses_duplicate_issue(
    controller: types.ModuleType,
) -> None:
    candidates = controller.build_candidates(
        [issue(501, "bug", "user-reported", "factory:unowned")],
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


def test_stale_fixed_lease_releases_but_live_worker_is_not_stolen(
    controller: types.ModuleType,
) -> None:
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


def test_chatgpt_factory_lease_is_not_reaped_using_fixed_model_run_state(
    controller: types.ModuleType,
) -> None:
    assert not controller.lease_is_stale(
        "factory:3",
        active_fixed_workers=set(),
        latest_activity_epoch=None,
        now_epoch=10_000,
    )


def test_local_lease_requires_explicit_stale_activity_evidence(
    controller: types.ModuleType,
) -> None:
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


def test_invalid_timeout_environment_falls_back_safely(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACTORY_TEST_TIMEOUT", "garbage")
    assert controller.env_positive_int("FACTORY_TEST_TIMEOUT", 120) == 120
    monkeypatch.setenv("FACTORY_TEST_TIMEOUT", "0")
    assert controller.env_positive_int("FACTORY_TEST_TIMEOUT", 120) == 120


def test_run_gh_converts_subprocess_timeout_to_controlled_error(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=120)

    monkeypatch.setattr(controller.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        controller.run_gh(["api", "rate_limit"])


def test_assign_candidate_writes_nothing_when_linked_issue_is_owned(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = controller.Candidate(
        "pr",
        1601,
        2,
        3,
        "2026-08-16T12:00:00Z",
        linked_issue=601,
    )
    monkeypatch.setattr(
        controller,
        "target_json",
        lambda number: {"state": "open"} if number == 601 else {"labels": []},
    )
    monkeypatch.setattr(controller, "target_still_unowned", lambda number: number != 601)
    writes: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        controller,
        "replace_factory_labels",
        lambda *args: writes.append(args),
    )

    assert controller.assign_candidate(candidate, "13") is False
    assert writes == []


def test_assign_candidate_rolls_first_target_back_when_second_write_fails(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = controller.Candidate(
        "pr",
        1602,
        2,
        3,
        "2026-08-16T12:00:00Z",
        linked_issue=602,
    )
    monkeypatch.setattr(controller, "target_json", lambda number: {"state": "open"})
    monkeypatch.setattr(controller, "target_still_unowned", lambda number: True)
    monkeypatch.setattr(controller, "target_owned_by", lambda number, owner: True)
    calls: list[tuple[int, str, str | None]] = []

    def replace(number: int, owner: str, stage: str | None = None) -> None:
        calls.append((number, owner, stage))
        if number == 1602 and owner == "factory:13":
            raise RuntimeError("write failed")

    monkeypatch.setattr(controller, "replace_factory_labels", replace)

    with pytest.raises(RuntimeError, match="write failed"):
        controller.assign_candidate(candidate, "13")

    assert (602, "factory:unowned", None) in calls


def test_pr_assignment_preserves_existing_workflow_stage(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = controller.Candidate("pr", 1603, 2, 3, "2026-08-16T12:00:00Z")
    monkeypatch.setattr(controller, "target_still_unowned", lambda number: True)
    monkeypatch.setattr(controller, "target_owned_by", lambda number, owner: True)
    calls: list[tuple[int, str, str | None]] = []
    monkeypatch.setattr(
        controller,
        "replace_factory_labels",
        lambda number, owner, stage=None: calls.append((number, owner, stage)),
    )

    assert controller.assign_candidate(candidate, "13") is True
    assert calls == [(1603, "factory:13", None)]


def test_assign_candidate_verifies_post_write_owner(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = controller.Candidate("issue", 603, 1, 3, "2026-08-16T12:00:00Z")
    monkeypatch.setattr(controller, "target_still_unowned", lambda number: True)
    monkeypatch.setattr(controller, "target_owned_by", lambda number, owner: False)
    writes: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        controller,
        "replace_factory_labels",
        lambda *args: writes.append(args),
    )

    assert controller.assign_candidate(candidate, "13") is False
    assert writes == [(603, "factory:13", "factory:building")]


def test_reconcile_does_not_release_active_fixed_worker(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(controller, "active_fixed_workers", lambda: {13})
    monkeypatch.setattr(controller, "owned_targets", lambda: [(701, "factory:13")])
    writes: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        controller,
        "replace_factory_labels",
        lambda *args: writes.append(args),
    )

    assert controller.reconcile_stale_leases(now_epoch=10_000) == []
    assert writes == []


def test_replace_factory_labels_preserves_existing_stage(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        controller,
        "target_json",
        lambda number: {
            "labels": [
                {"name": "bug"},
                {"name": "factory"},
                {"name": "factory:unowned"},
                {"name": "factory:changes-requested"},
            ]
        },
    )
    payloads: list[dict[str, Any]] = []

    def fake_run(
        args: list[str], *, input_json: Any | None = None, check: bool = True
    ) -> str:
        assert input_json is not None
        payloads.append(input_json)
        return ""

    monkeypatch.setattr(controller, "run_gh", fake_run)

    controller.replace_factory_labels(801, "factory:13")

    assert set(payloads[0]["labels"]) == {
        "bug",
        "factory",
        "factory:13",
        "factory:changes-requested",
    }


def test_ci_pr_with_passing_required_checks_is_not_executable(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = controller.Candidate("pr", 901, 3, 2, "2026-08-16T12:00:00Z")
    monkeypatch.setattr(
        controller,
        "target_json",
        lambda number: {"labels": [{"name": "factory:ci"}]},
    )
    monkeypatch.setattr(controller, "required_checks_failed", lambda number: False)

    assert controller.candidate_is_live_executable(candidate) is False


def test_active_fixed_workers_paginates_all_active_run_states(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    responses = iter(
        [
            [
                {
                    "workflow_runs": [
                        {"id": 1, "display_title": "Factory 13 · fixed-model entry"}
                    ]
                }
            ],
            [
                {
                    "workflow_runs": [
                        {"id": 2, "display_title": "Factory 29 · fixed-model entry"}
                    ]
                }
            ],
        ]
    )

    def fake_gh_json(args: list[str], **kwargs: Any) -> Any:
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(controller, "gh_json", fake_gh_json)

    assert controller.active_fixed_workers() == {13, 29}
    assert all("--paginate" in args and "--slurp" in args for args in calls)


def test_active_fixed_workers_fails_closed_when_live_run_identity_is_unknown(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = iter(
        [
            [{"workflow_runs": [{"id": 99, "display_title": "Fixed Model Factory Entry"}]}],
            [{"workflow_runs": []}],
            [[]],
        ]
    )
    monkeypatch.setattr(
        controller,
        "gh_json",
        lambda args, **kwargs: next(responses),
    )

    with pytest.raises(RuntimeError, match="unable to resolve worker identity"):
        controller.active_fixed_workers()


def test_busy_fixed_worker_is_not_given_a_second_assignment(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(controller, "worker_has_active_lease", lambda worker: True)
    monkeypatch.setattr(
        controller,
        "list_issues",
        lambda: (_ for _ in ()).throw(AssertionError("must not rank new work")),
    )

    assert controller.assign("13") is None


def test_one_dispatch_batch_plans_distinct_targets(controller: types.ModuleType) -> None:
    candidates = [
        controller.Candidate("issue", 601, 1, 3, "2026-08-16T12:00:00Z"),
        controller.Candidate("issue", 602, 3, 2, "2026-08-16T11:00:00Z"),
    ]

    plan = controller.plan_distinct_assignments(candidates, ["13", "29"])

    assert plan["13"].number == 601
    assert plan["29"].number == 602


def test_active_worker_no_longer_performs_repo_wide_selection_or_merging() -> None:
    worker = (
        REPO_ROOT / ".github/scripts/free-model-factory-worker.sh"
    ).read_text(encoding="utf-8")

    assert "choose_existing_pr" not in worker
    assert "choose_ranked_issues" not in worker
    assert "claim_from_pool" not in worker
    assert "select_controller_assignment" in worker
    assert "controller-assignment-read-failed" in worker
    assert "exiting without repo-wide selection" in worker
    assert "handing it to the merge controller" in worker
    assert 'gh pr merge "$NUMBER"' not in worker


def test_dispatcher_validates_controller_assignment_and_survives_dispatch_failure() -> None:
    dispatcher = (
        REPO_ROOT / ".github/workflows/free-model-factory-dispatch.yml"
    ).read_text(encoding="utf-8")

    assert "group: fixed-model-factory-dispatch" in dispatcher
    assert 'python3 "$controller" reconcile' in dispatcher
    assert 'if ! assignment="$(python3 "$controller" assign --worker "$worker")"' in dispatcher
    assert "unusable controller response" in dispatcher
    assert "while (( attempt <= 3 ))" in dispatcher
    assert 'python3 "$controller" release --worker "$worker"' in dispatcher
    assert 'dispatch_assigned_worker "$worker" || dispatch_failures=' in dispatcher
    assert "later workers were still attempted" in dispatcher


def test_entry_run_name_exposes_queued_worker_identity() -> None:
    entry = (
        REPO_ROOT / ".github/workflows/free-model-factory-entry.yml"
    ).read_text(encoding="utf-8")

    assert "run-name: Factory ${{ inputs.worker }} · fixed-model entry" in entry
