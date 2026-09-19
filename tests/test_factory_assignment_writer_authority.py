"""Regression tests for the single factory assignment writer invariant."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_PATH = REPO_ROOT / ".github/scripts/factory-work-controller.py"
REPOSITORY = "JoshCLWren/comic-pile"
DISPATCHER_REF = (
    f"{REPOSITORY}/.github/workflows/fixed-model-factory-dispatch.yml@refs/heads/main"
)


@pytest.fixture()
def controller() -> types.ModuleType:
    """Load a fresh controller module so environment-gated tests stay isolated."""
    name = "factory_work_controller_assignment_authority"
    spec = importlib.util.spec_from_file_location(name, CONTROLLER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def set_actions_identity(
    monkeypatch: pytest.MonkeyPatch, *, workflow_ref: str, workflow_name: str
) -> None:
    """Set the GitHub Actions identity inputs used by writer authorization."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", workflow_ref)
    monkeypatch.setenv("GITHUB_WORKFLOW", workflow_name)


def test_non_dispatcher_actions_workflow_cannot_create_fixed_lease(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second Actions workflow cannot mutate an unowned target to factory:N."""
    set_actions_identity(
        monkeypatch,
        workflow_ref=(
            f"{REPOSITORY}/.github/workflows/factory-completion-drain.yml@refs/heads/main"
        ),
        workflow_name="Factory Completion Drain",
    )
    monkeypatch.setattr(
        controller,
        "target_json",
        lambda number: {"labels": [{"name": "factory:unowned"}]},
    )
    writes: list[tuple[list[str], object | None]] = []

    def fake_run(
        args: list[str], *, input_json: object | None = None, check: bool = True
    ) -> str:
        writes.append((args, input_json))
        return ""

    monkeypatch.setattr(controller, "run_gh", fake_run)

    with pytest.raises(RuntimeError, match="fixed-model-factory-dispatch.yml"):
        controller.replace_factory_labels(2736, "factory:41", "factory:building")

    assert writes == []


def test_dispatcher_actions_workflow_can_create_fixed_lease(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dispatcher workflow file remains authorized to perform the mutation."""
    set_actions_identity(
        monkeypatch,
        workflow_ref=DISPATCHER_REF,
        workflow_name="Fixed Model Factory Dispatcher",
    )
    monkeypatch.setattr(
        controller,
        "target_json",
        lambda number: {"labels": [{"name": "factory:unowned"}]},
    )
    writes: list[tuple[list[str], object | None]] = []

    def fake_run(
        args: list[str], *, input_json: object | None = None, check: bool = True
    ) -> str:
        writes.append((args, input_json))
        return ""

    monkeypatch.setattr(controller, "run_gh", fake_run)

    controller.replace_factory_labels(2736, "factory:41", "factory:building")

    assert len(writes) == 1
    payload = cast(dict[str, Any], writes[0][1])
    assert "factory:41" in cast(list[str], payload["labels"])


def test_matching_display_name_cannot_spoof_dispatcher_workflow_file(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duplicate workflow display name cannot gain numbered-lease authority."""
    set_actions_identity(
        monkeypatch,
        workflow_ref=(
            f"{REPOSITORY}/.github/workflows/not-the-dispatcher.yml@refs/heads/main"
        ),
        workflow_name="Fixed Model Factory Dispatcher",
    )

    assert controller.assignment_writer_authorized() is False


def test_missing_workflow_ref_is_not_authorized_in_actions(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actions runs fail closed when GitHub does not supply workflow identity."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.delenv("GITHUB_WORKFLOW_REF", raising=False)
    monkeypatch.setenv("GITHUB_WORKFLOW", "Fixed Model Factory Dispatcher")

    assert controller.assignment_writer_authorized() is False


def test_non_actions_process_remains_authorized(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local operator and test invocations are not gated by Actions identity."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_WORKFLOW_REF", raising=False)

    assert controller.assignment_writer_authorized() is True


def test_release_to_unowned_is_allowed_outside_dispatcher(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recovery workflows may release leases without gaining assignment authority."""
    set_actions_identity(
        monkeypatch,
        workflow_ref=(
            f"{REPOSITORY}/.github/workflows/free-model-factory-run.yml@refs/heads/main"
        ),
        workflow_name="Fixed Model Factory Entry",
    )
    monkeypatch.setattr(
        controller,
        "target_json",
        lambda number: {
            "labels": [
                {"name": "factory"},
                {"name": "factory:41"},
                {"name": "factory:review"},
            ]
        },
    )
    writes: list[dict[str, Any]] = []

    def fake_run(
        args: list[str], *, input_json: object | None = None, check: bool = True
    ) -> str:
        assert isinstance(input_json, dict)
        writes.append(input_json)
        return ""

    monkeypatch.setattr(controller, "run_gh", fake_run)

    controller.replace_factory_labels(2736, "factory:unowned")

    assert writes
    assert "factory:unowned" in writes[0]["labels"]


def test_assign_candidate_rechecks_worker_lease_at_mutation_boundary(
    controller: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker that became busy after selection receives no second target write."""
    candidate = controller.Candidate(
        "issue",
        2736,
        1,
        1,
        "2026-09-19T15:00:00Z",
    )
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(controller, "target_still_unowned", lambda number: True)
    monkeypatch.setattr(controller, "worker_has_active_lease", lambda worker: True)
    writes: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        controller,
        "replace_factory_labels",
        lambda *args: writes.append(args),
    )

    assert controller.assign_candidate(candidate, "41") is False
    assert writes == []
