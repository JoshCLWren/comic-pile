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


def test_missing_tool_metadata_does_not_reject_exact_ranked_free_model() -> None:
    """Unknown capability metadata remains eligible for later integration proof."""
    assert POOL.qualified_models(
        {"data": [{"id": "vendor/unknown:free"}]},
        {"models": [{"model": "vendor/unknown", "score": 0.8}]},
    ) == ["vendor/unknown:free"]


def test_empty_qualified_pool_uses_non_expanding_sentinel() -> None:
    """An empty authoritative result must not leave stale executable members."""
    assert POOL.NO_CAPACITY_MODEL == "__no_qualified_free_capacity__"


def _combos() -> list[dict[str, object]]:
    """Build both expected cascades with distinct preserved configs."""
    return [
        {"id": "small", "name": "free-cascade-small", "config": {"validate": True}},
        {"id": "big", "name": "free-cascade-big", "config": {}},
    ]


def test_first_update_failure_still_attempts_second_and_fails_closed() -> None:
    """Partial management failure cannot skip the second sentinel update."""
    calls: list[str] = []
    readback = _combos()

    def put(identifier: str, payload: dict[str, object]) -> None:
        calls.append(identifier)
        if identifier == "small":
            raise OSError("first target unavailable")
        models = payload["models"]
        assert isinstance(models, list)
        readback[1] = {**readback[1], "strategy": payload["strategy"], "models": [
            {**model, "id": "server-generated-id"} for model in models
        ]}

    ok, failures = POOL.reconcile_combos(_combos(), [POOL.NO_CAPACITY_MODEL], put, lambda: readback)
    assert calls == ["small", "big"]
    assert not ok
    assert any("small update failed" in failure for failure in failures)


def test_missing_expected_cascade_is_rejected_before_mutation() -> None:
    """A partial combo listing cannot be reported as successful reconciliation."""
    calls: list[str] = []
    ok, failures = POOL.reconcile_combos(
        _combos()[:1], ["vendor/model:free"], lambda identifier, payload: calls.append(identifier), lambda: [],
    )
    assert not ok
    assert calls == []
    assert failures == ["missing cascade: free-cascade-big"]


def test_readback_mismatch_is_failure() -> None:
    """Successful PUT responses are insufficient without exact readback."""
    combos = _combos()
    ok, failures = POOL.reconcile_combos(
        combos, ["vendor/model:free"], lambda identifier, payload: None,
        lambda: [{**combo, "strategy": "priority", "models": []} for combo in combos],
    )
    assert not ok
    assert "free-cascade-small readback mismatch" in failures


def test_readback_rejects_semantic_order_mismatch() -> None:
    """Generated IDs are ignored, but owned membership order is verified."""
    combos = _combos()
    actual = [
        {**combo, "strategy": "priority", "models": [{"kind": "model", "model": "vendor/other:free", "providerId": "openrouter", "weight": 0}]}
        for combo in combos
    ]
    ok, failures = POOL.reconcile_combos(
        combos, ["vendor/model:free"], lambda identifier, payload: None, lambda: actual,
    )
    assert not ok
    assert "free-cascade-small readback mismatch" in failures


def test_successful_reconciliation_is_idempotent() -> None:
    """The same desired payload can be applied and verified repeatedly."""
    combos = _combos()
    state = _combos()

    def put(identifier: str, payload: dict[str, object]) -> None:
        for index, combo in enumerate(state):
            if combo["id"] == identifier:
                state[index] = {**combo, **payload}

    assert POOL.reconcile_combos(combos, ["vendor/model:free"], put, lambda: state)[0]
    assert POOL.reconcile_combos(state, ["vendor/model:free"], put, lambda: state)[0]


def test_successful_readback_ignores_generated_ids_on_both_cascades() -> None:
    """Both server-generated entry IDs are ignored after successful updates."""
    expected = _combos()
    state = _combos()

    def put(identifier: str, payload: dict[str, object]) -> None:
        for index, combo in enumerate(state):
            if combo["id"] == identifier:
                models = payload["models"]
                assert isinstance(models, list)
                state[index] = {
                    **combo,
                    **payload,
                    "models": [
                        {**model, "id": f"server-generated-{identifier}"}
                        for model in models
                    ],
                }

    ok, failures = POOL.reconcile_combos(expected, ["vendor/model:free"], put, lambda: state)
    assert ok
    assert failures == []


def test_sentinel_readback_accepts_openrouter_qualified_name_on_both_cascades() -> None:
    """OmniRoute's provider-qualified no-capacity sentinel is equivalent."""
    expected = _combos()
    actual = [
        {
            **combo,
            "strategy": "priority",
            "models": [{"kind": "model", "model": "openrouter/" + POOL.NO_CAPACITY_MODEL,
                        "providerId": "openrouter", "weight": 0}],
        }
        for combo in expected
    ]

    ok, failures = POOL.reconcile_combos(
        expected, [POOL.NO_CAPACITY_MODEL], lambda identifier, payload: None, lambda: actual,
    )
    assert ok
    assert failures == []


def test_sentinel_equivalence_does_not_normalize_executable_model_names() -> None:
    """Provider/name prefixes remain significant for executable models."""
    combos = _combos()
    actual = [
        {
            **combo,
            "strategy": "priority",
            "models": [{"kind": "model", "model": "openrouter/vendor/model:free",
                        "providerId": "openrouter", "weight": 0}],
        }
        for combo in combos
    ]

    ok, failures = POOL.reconcile_combos(
        combos, ["vendor/model:free"], lambda identifier, payload: None, lambda: actual,
    )
    assert not ok
    assert "free-cascade-small readback mismatch" in failures


def test_sentinel_equivalence_requires_openrouter_provider() -> None:
    """The sentinel exception cannot hide a provider identity mismatch."""
    combos = _combos()
    actual = [
        {
            **combo,
            "strategy": "priority",
            "models": [{"kind": "model", "model": "openrouter/" + POOL.NO_CAPACITY_MODEL,
                        "providerId": "other", "weight": 0}],
        }
        for combo in combos
    ]

    ok, failures = POOL.reconcile_combos(
        combos, [POOL.NO_CAPACITY_MODEL], lambda identifier, payload: None, lambda: actual,
    )
    assert not ok
    assert "free-cascade-small readback mismatch" in failures
