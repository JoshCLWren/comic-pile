"""Regression coverage for controller-owned passive factory CI reconciliation."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RECONCILER_PATH = REPO_ROOT / ".github/scripts/factory-ci-reconciler.py"
HEAD = "a" * 40


@pytest.fixture(scope="module")
def reconciler() -> ModuleType:
    """Load the passive CI reconciler once for focused runtime tests."""
    spec = importlib.util.spec_from_file_location(
        "factory_ci_reconciler_test_runtime",
        RECONCILER_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ci_pr(*, owner: str = "factory:unowned") -> dict[str, Any]:
    """Build one open factory CI PR fixture."""
    return {
        "state": "OPEN",
        "isDraft": False,
        "headRefOid": HEAD,
        "headRefName": "factory/16-1111-nvidia",
        "body": "Worker: opencode-free-model-factory-16",
        "labels": [
            {"name": "factory"},
            {"name": owner},
            {"name": "factory:ci"},
        ],
    }


def linked_issue(*, owner: str = "factory:unowned") -> dict[str, Any]:
    """Build one open linked factory issue fixture."""
    return {
        "state": "open",
        "labels": [
            {"name": "factory"},
            {"name": owner},
        ],
    }


def arrange(
    reconciler: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    authorized: bool = True,
    gate: dict[str, str] | None = None,
    owner: str = "factory:unowned",
    linked_owner: str = "factory:unowned",
) -> list[tuple[int, str, str]]:
    """Install deterministic PR state and capture lifecycle label writes."""
    controller = reconciler.review_controller
    monkeypatch.setattr(controller, "pr_json", lambda number: ci_pr(owner=owner))
    monkeypatch.setattr(
        controller,
        "target_json",
        lambda number: linked_issue(owner=linked_owner),
    )
    monkeypatch.setattr(
        reconciler,
        "exact_head_is_authorized",
        lambda number, pr: authorized,
    )
    monkeypatch.setattr(
        controller,
        "mechanical_merge_gate",
        lambda number, head: gate
        or {"decision": "retry", "reason": "required checks are not terminal: PENDING"},
    )
    writes: list[tuple[int, str, str]] = []
    monkeypatch.setattr(
        controller,
        "replace_factory_labels",
        lambda number, next_owner, stage: writes.append((number, next_owner, stage)),
    )
    return writes


def test_pending_checks_stay_in_ci(
    reconciler: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pending exact-head checks need no model and no stage mutation."""
    writes = arrange(
        reconciler,
        monkeypatch,
        gate={"decision": "retry", "reason": "required checks are not terminal: PENDING"},
    )

    result = reconciler.reconcile_ci_pr(1513)

    assert result["status"] == "ci"
    assert writes == []


def test_failed_checks_stay_ci_and_remain_worker_repairable(
    reconciler: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed required check stays in CI for work-controller repair adoption."""
    writes = arrange(
        reconciler,
        monkeypatch,
        gate={"decision": "deny", "reason": "required checks failed: FAILURE"},
    )

    result = reconciler.reconcile_ci_pr(1513)

    assert result["status"] == "failed-ci"
    assert writes == []


def test_stale_exact_head_approval_returns_to_review(
    reconciler: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing exact-head semantic authorization cannot survive in the CI lane."""
    writes = arrange(reconciler, monkeypatch, authorized=False)

    result = reconciler.reconcile_ci_pr(1513)

    assert result["status"] == "review"
    assert writes == [(1513, "factory:unowned", "factory:review")]


def test_conflict_moves_to_changes_requested(
    reconciler: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A merge conflict becomes explicit executable repair work."""
    writes = arrange(
        reconciler,
        monkeypatch,
        gate={"decision": "deny", "reason": "pull request has merge conflicts"},
    )

    result = reconciler.reconcile_ci_pr(1513)

    assert result["status"] == "changes-requested"
    assert writes == [(1513, "factory:unowned", "factory:changes-requested")]


def test_green_authorized_ci_promotes_directly_to_ready(
    reconciler: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Green exact-head CI promotes without dispatching a model worker."""
    writes = arrange(
        reconciler,
        monkeypatch,
        gate={"decision": "pass", "reason": "all exact-head mechanical gates passed"},
    )

    result = reconciler.reconcile_ci_pr(1513)

    assert result["status"] == "ready"
    assert writes == [(1513, "factory:unowned", "factory:ready")]


def test_live_pr_worker_ownership_is_never_stolen(
    reconciler: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passive reconciliation cannot race a worker already repairing this PR."""
    writes = arrange(reconciler, monkeypatch, owner="factory:17")

    result = reconciler.reconcile_ci_pr(1513)

    assert result["status"] == "owned"
    assert result["owner"] == "factory:17"
    assert writes == []


def test_live_linked_issue_worker_ownership_is_never_stolen(
    reconciler: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial issue/PR lease handoff fails closed instead of racing assignment."""
    writes = arrange(reconciler, monkeypatch, linked_owner="factory:17")

    result = reconciler.reconcile_ci_pr(1513)

    assert result["status"] == "linked-issue-owned"
    assert result["owner"] == "factory:17"
    assert writes == []
