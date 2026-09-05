"""Tests for role-aware native OmniRoute factory routing."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


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
