"""Tests for the repository-managed OmniRoute pool reconciler."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(".github/scripts/reconcile_omniroute_free_pool.py")
spec = importlib.util.spec_from_file_location("pool_reconciler", SCRIPT)
assert spec and spec.loader
POOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(POOL)


def test_new_exact_ranked_free_tool_model_is_admitted() -> None:
    """A newly catalogued exact Arena identity enters the pool."""
    models = POOL.qualified_models(
        {"data": [{"id": "openrouter/vendor/new:free", "capabilities": {"tool_calling": True}}]},
        {"models": [{"model": "vendor/new", "score": 0.8}]},
    )
    assert models == ["openrouter/vendor/new:free"]


def test_unranked_successful_model_is_excluded() -> None:
    """Catalog presence and successful transport do not establish quality."""
    assert POOL.qualified_models(
        {"data": [{"id": "vendor/unranked:free", "capabilities": {"tool_calling": True}}]},
        {"models": []},
    ) == []


def test_paid_or_non_tool_model_is_excluded() -> None:
    """Free-only and tool-capability admission gates are both enforced."""
    catalog = {
        "data": [
            {"id": "vendor/paid", "capabilities": {"tool_calling": True}},
            {"id": "vendor/no-tools:free", "capabilities": {"tool_calling": False}},
        ]
    }
    ranking = {"models": [{"model": "vendor/paid", "score": 0.9}, {"model": "vendor/no-tools", "score": 0.8}]}
    assert POOL.qualified_models(catalog, ranking) == []
