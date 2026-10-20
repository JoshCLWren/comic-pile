"""factory:local is a hard local/manual stop for claim, continuation, CI promotion, and merge."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import factory_eligibility as eligibility  # noqa: E402
import factory_work_policy as policy  # noqa: E402

HEAD = "d" * 40


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("module", [policy, eligibility])
def test_local_owner_dominates_coexisting_worker_label(module) -> None:
    labels = {"factory", "factory:45", "factory:local", "factory:changes-requested"}
    assert module.owner_of(labels) == "factory:local"
    assert module.owner_of({"factory:local", "factory:unowned"}) == "factory:local"
    assert module.owner_of({"factory:45"}) == "factory:45"


def test_local_hold_is_not_claimable_and_never_stale() -> None:
    issue = {
        "number": 3609,
        "state": "OPEN",
        "body": "",
        "labels": [{"name": "factory"}, {"name": "factory:local"}],
    }
    assert policy.issue_is_static_candidate(issue, suppressing_pr_issues=set()) is False
    assert not policy.lease_is_stale(
        "factory:local",
        active_fixed_workers=set(),
        latest_activity_epoch=0,
        now_epoch=10**10,
    )


def test_worker_continuation_ignores_local_held_target(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = _load("factory_work_controller_local_hold", "factory-work-controller.py")
    held = {
        "number": 3956,
        "labels": [{"name": "factory"}, {"name": "factory:45"}, {"name": "factory:local"}],
    }
    monkeypatch.setattr(controller, "list_issues", lambda: [])
    monkeypatch.setattr(controller, "list_prs", lambda: [held])
    assert controller.owned_targets() == [(3956, "factory:local")]
    assert controller.worker_has_active_lease("45") is False


def _review_controller():
    return _load("factory_review_controller_local_hold", "factory-review-controller.py")


def _held_pr(stage: str) -> dict:
    return {
        "state": "OPEN",
        "headRefOid": HEAD,
        "headRefName": "factory/45-3953-opencode-free",
        "body": "Closes #3953",
        "labels": [{"name": "factory"}, {"name": "factory:local"}, {"name": stage}],
    }


def test_reconcile_ci_never_promotes_or_hands_off_local_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _review_controller()
    monkeypatch.setattr(controller, "pr_json", lambda _pr: _held_pr("factory:ci"))
    monkeypatch.setattr(
        controller, "required_checks_gate", lambda _pr: {"decision": "deny", "reason": "red"}
    )
    writes: list[tuple] = []
    monkeypatch.setattr(controller, "replace_factory_labels", lambda *args: writes.append(args))
    monkeypatch.setattr(
        controller, "post_review_comment", lambda **_kw: writes.append(("comment",))
    )

    assert controller.reconcile_ci_pr(3956) == {"pr": 3956, "status": "local-hold"}
    assert writes == []


def test_authorize_ready_refuses_local_hold_without_relabeling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _review_controller()
    monkeypatch.setattr(controller, "pr_json", lambda _pr: _held_pr("factory:ready"))
    writes: list[tuple] = []
    monkeypatch.setattr(controller, "replace_factory_labels", lambda *args: writes.append(args))

    result = controller.authorize_ready(3956)

    assert result["authorized"] is False
    assert result["reason"] == "factory:local hold"
    assert writes == []


@pytest.mark.parametrize(
    "workflow", ["factory-ready-merge-drain.yml", "fixed-model-factory-dispatch.yml"]
)
def test_merge_drains_skip_local_hold_before_authorization(workflow: str) -> None:
    text = (REPO_ROOT / ".github" / "workflows" / workflow).read_text()
    loop = text.index("read -r pr ", text.index('for candidate in "${ready_prs[@]}"'))
    guard = text.index("*,factory:local,*)", loop)
    assert guard < text.index('authorized --pr "$pr"', loop)
    assert "continue" in text[guard : guard + 300]
