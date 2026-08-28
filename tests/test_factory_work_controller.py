"""Regression coverage for centralized factory assignment and leases."""

from __future__ import annotations

import importlib.util
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
    """Verify user report beats ordinary product and e2e."""
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
    """Verify ordinary product beats e2e even when e2e is newer."""
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
    """Verify e2e is selected when higher lanes are empty."""
    candidates = controller.build_candidates(
        [issue(301, "bug", "e2e-discovered", "factory:unowned")],
        [],
    )
    assert [(candidate.number, candidate.lane) for candidate in candidates] == [(301, 4)]


def test_equal_priority_items_drain_oldest_first(
    controller: types.ModuleType,
) -> None:
    """Verify equal priority items drain oldest first so backlogged work cannot starve."""
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
    assert [candidate.number for candidate in candidates] == [310, 311]


def test_user_bug_pr_repair_inherits_priority_without_worker_affinity(
    controller: types.ModuleType,
) -> None:
    """Verify user bug pr repair inherits priority without worker affinity."""
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
    """Verify controller uses only canonical worker issue branch shape."""
    assert controller.linked_issue_from_branch("factory/27-401-repair") == 401
    assert controller.linked_issue_from_branch("factory/27-repair") is None
    assert controller.linked_issue_from_branch("factory/401-repair") is None


def test_draft_pr_suppresses_linked_issue_until_pr_closes(
    controller: types.ModuleType,
) -> None:
    """A draft canonical PR still owns issue identity until explicitly closed."""
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
    assert candidates == []


def test_blocked_pr_suppresses_linked_issue_until_pr_closes(
    controller: types.ModuleType,
) -> None:
    """A blocked canonical PR cannot silently spawn a replacement implementation."""
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
    assert candidates == []


def test_ready_pr_is_reserved_for_merge_controller_and_suppresses_duplicate_issue(
    controller: types.ModuleType,
) -> None:
    """Verify ready pr is reserved for merge controller and suppresses duplicate issue."""
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


def test_urgent_defects_bypass_wip_but_not_review_backlog_saturation(
    controller: types.ModuleType,
) -> None:
    """Urgent defects bypass worker WIP only; main-breakage alone beats backlog."""
    backlog = [
        pr(
            400 + index,
            f"factory/{10 + index}-990-fix",
            "factory:unowned",
            "factory:review",
            created=f"2026-08-20T12:00:{index:02d}Z",
        )
        for index in range(20)
    ]
    ordinary = issue(501, "enhancement", "factory:unowned")
    urgent = issue(502, "bug", "user-reported", "factory:unowned")
    breakage = issue(503, "bug", "main-breakage", "factory:unowned")

    candidates = controller.build_candidates([ordinary, urgent, breakage], backlog)

    produced = {candidate.number for candidate in candidates if candidate.kind == "issue"}
    assert "pr" in {candidate.kind for candidate in candidates}
    assert 501 not in produced, "ordinary issue intake must stop under backlog"
    assert 502 not in produced, "urgent user-reported defects are stopped by backlog saturation"
    assert 503 in produced, "main-breakage remains executable under backlog saturation"

    wip = [
        pr(
            430 + index,
            f"factory/{40 + index}-991-fix",
            f"factory:{20 + index}",
            "factory:review",
            created=f"2026-08-20T12:00:{index:02d}Z",
        )
        for index in range(5)
    ]
    wip_candidates = controller.build_candidates([ordinary, urgent], wip)

    wip_produced = {
        candidate.number for candidate in wip_candidates if candidate.kind == "issue"
    }
    assert 501 not in wip_produced, "ordinary issue intake must stop under worker WIP"
    assert 502 in wip_produced, "urgent user-reported defects still bypass worker WIP"
