"""Tests for role-aware native OmniRoute factory routing."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "scripts"
    / "factory_omniroute_route.py"
)


def load_module() -> ModuleType:
    """Load the routing helper without packaging .github."""
    spec = importlib.util.spec_from_file_location("factory_omniroute_route", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ROUTES = load_module()


def test_issue_implementation_uses_free_coding_route() -> None:
    assert ROUTES.route_for_assignment("issue") == "auto/coding:free"


def test_pr_repair_uses_free_coding_route() -> None:
    assert (
        ROUTES.route_for_assignment("pr", "factory:changes-requested")
        == "auto/coding:free"
    )


def test_exact_head_review_uses_free_reasoning_route() -> None:
    assert (
        ROUTES.route_for_assignment("pr", "factory:review")
        == "auto/reasoning:free"
    )


def test_worker_applies_assignment_route_without_candidate_health() -> None:
    """The session wrapper resolves the native intent after assignment."""
    worker = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "scripts"
        / "free-model-factory-worker.sh"
    ).read_text(encoding="utf-8")

    assert "factory_omniroute_route.py" in worker
    assert 'MODEL="$effective_route"' in worker
    assert 'RUNTIME_MODEL="omniroute/${effective_route}"' in worker
    assert "factory_provider_candidates.py" not in worker
    assert "factory_candidate_health.py" not in worker
    assert "selected native OmniRoute intent route" in worker
    assert "FACTORY_ROUTE_OVERRIDE" in worker
    assert "TEMPORARY capacity bridge" in worker


def test_capacity_bridge_defaults_to_best_free() -> None:
    """The temporary coding-intent outage bridge is auto/best-free."""
    assert ROUTES.CAPACITY_BRIDGE_ROUTE == "auto/best-free"
    assert ROUTES.capacity_bridge_enabled() is True
    assert ROUTES.capacity_bridge_route() == "auto/best-free"


def test_capacity_bridge_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """FACTORY_OMNIROUTE_CAPACITY_BRIDGE=off is the one-flag revert."""
    monkeypatch.setenv("FACTORY_OMNIROUTE_CAPACITY_BRIDGE", "off")
    assert ROUTES.capacity_bridge_enabled() is False
    assert ROUTES.capacity_bridge_route() == ""


def test_coding_skip_falls_back_to_best_free() -> None:
    """ALL_TARGETS_SKIPPED on auto/coding:free retries auto/best-free."""
    log = (
        "Error: Service temporarily unavailable: "
        "all targets were skipped by pre-dispatch filters"
    )
    assert (
        ROUTES.next_route_after_smoke_failure("auto/coding:free", 1, log)
        == "auto/best-free"
    )


def test_coding_timeout_falls_back_to_best_free() -> None:
    """A hung coding-intent smoke is bridge-eligible."""
    assert (
        ROUTES.next_route_after_smoke_failure("auto/coding:free", 124, "")
        == "auto/best-free"
    )


def test_review_skip_does_not_fall_back_to_coding_free() -> None:
    """Review still prefers reasoning; the bridge is best-free, never coding:free."""
    log = "all targets were skipped by pre-dispatch filters"
    assert (
        ROUTES.next_route_after_smoke_failure("auto/reasoning:free", 1, log)
        == "auto/best-free"
    )
    assert (
        ROUTES.next_route_after_smoke_failure("auto/reasoning:free", 1, log)
        != "auto/coding:free"
    )


def test_non_skip_failure_does_not_bridge() -> None:
    """A hard model error does not silently switch to best-free."""
    assert (
        ROUTES.next_route_after_smoke_failure(
            "auto/coding:free",
            1,
            "HTTP 410 Gone: model permanently retired",
        )
        == ""
    )


def test_bridge_off_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disabling the temporary bridge leaves a coding skip unretried."""
    monkeypatch.setenv("FACTORY_OMNIROUTE_CAPACITY_BRIDGE", "off")
    log = "all targets were skipped by pre-dispatch filters"
    assert ROUTES.next_route_after_smoke_failure("auto/coding:free", 1, log) == ""
