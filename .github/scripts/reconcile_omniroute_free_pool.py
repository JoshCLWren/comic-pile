#!/usr/bin/env python3
"""Reconcile stable OmniRoute factory pools from fresh free catalog evidence."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

ARENA_URL = "https://api.wulong.dev/arena-ai-leaderboards/v1/leaderboard?name=code"
CASCADE_NAMES = ("free-cascade-small", "free-cascade-big")
NO_CAPACITY_MODEL = "__no_qualified_free_capacity__"


def _get(url: str, key: str) -> Any:
    """Fetch one authenticated JSON document without exposing credentials."""
    headers = {"Authorization": f"Bearer {key}"} if key else {"User-Agent": "comic-pile-factory/1"}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _key(model: str) -> str:
    """Normalize only documented provider/free suffixes for exact matching."""
    value = model.lower()
    if value.startswith("openrouter/"):
        value = value[len("openrouter/") :]
    if value.endswith(":free"):
        value = value[:-5]
    return value


def qualified_models(catalog: dict[str, Any], ranking: dict[str, Any]) -> list[str]:
    """Return live free tool-capable models with exact current Arena identities."""
    models = ranking.get("models")
    if not isinstance(models, list):
        return []
    scores = {
        _key(item["model"]): float(item["score"])
        for item in models
        if isinstance(item, dict)
        and isinstance(item.get("model"), str)
        and isinstance(item.get("score"), (int, float))
    }
    candidates = catalog.get("data")
    if not isinstance(candidates, list):
        return []
    qualified = []
    for item in candidates:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        model = item["id"]
        capabilities = item.get("capabilities")
        if not model.endswith(":free") or (
            isinstance(capabilities, dict) and capabilities.get("tool_calling") is False
        ):
            continue
        if _key(model) not in scores:
            continue
        qualified.append(model)
    return sorted(set(qualified), key=lambda model: (-scores[_key(model)], model))


def reconcile_combos(
    combos: list[dict[str, Any]],
    selected_models: list[str],
    put_combo: Any,
    read_combos: Any,
) -> tuple[bool, list[str]]:
    """Update every expected cascade and verify exact post-mutation state."""
    by_name = {combo.get("name"): combo for combo in combos}
    missing = [name for name in CASCADE_NAMES if name not in by_name]
    if missing:
        return False, [f"missing cascade: {name}" for name in missing]
    members = [
        {"kind": "model", "model": model, "providerId": "openrouter", "weight": 0}
        for model in selected_models
    ]
    failures: list[str] = []

    def owned_models(value: object) -> list[dict[str, object]]:
        """Return only model-entry fields controlled by this reconciler."""
        if not isinstance(value, list):
            return []
        return [
            {
                field: item[field]
                for field in ("kind", "model", "providerId", "weight")
                if field in item
            }
            for item in value
            if isinstance(item, dict)
        ]

    def models_match(actual: object) -> bool:
        """Verify owned model fields, allowing only OmniRoute's sentinel rewrite."""
        actual_models = owned_models(actual)
        if len(actual_models) != len(members):
            return False
        for expected_model, actual_model in zip(members, actual_models, strict=True):
            if expected_model.get("kind") != actual_model.get("kind"):
                return False
            if expected_model.get("providerId") != actual_model.get("providerId"):
                return False
            if expected_model.get("weight") != actual_model.get("weight"):
                return False
            expected_name = expected_model.get("model")
            actual_name = actual_model.get("model")
            sentinel_readback = (
                expected_name == NO_CAPACITY_MODEL
                and expected_model.get("providerId") == "openrouter"
                and actual_name == f"openrouter/{NO_CAPACITY_MODEL}"
            )
            if expected_name != actual_name and not sentinel_readback:
                return False
        return True

    for name in CASCADE_NAMES:
        combo = by_name[name]
        payload = {"strategy": "priority", "models": members, "config": combo.get("config") or {}}
        try:
            put_combo(combo["id"], payload)
        except (OSError, KeyError, TypeError, ValueError) as error:
            failures.append(f"{name} update failed: {type(error).__name__}")
    try:
        readback = read_combos()
    except (OSError, KeyError, TypeError, ValueError) as error:
        failures.append(f"readback failed: {type(error).__name__}")
        return False, failures
    readback_by_name = {combo.get("name"): combo for combo in readback}
    for name in CASCADE_NAMES:
        combo = readback_by_name.get(name)
        expected = by_name[name]
        if (
            not isinstance(combo, dict)
            or combo.get("strategy") != "priority"
            or not models_match(combo.get("models"))
            or (combo.get("config") or {}) != (expected.get("config") or {})
        ):
            failures.append(f"{name} readback mismatch")
    return not failures, failures


def main() -> int:
    """Reconcile both stable pools or fail closed without changing them."""
    base = os.environ.get("OMNIROUTE_BASE_URL", "").rstrip("/")
    inference_key = os.environ.get("OMNIROUTE_API_KEY", "")
    management_key = os.environ.get("OMNIROUTE_MANAGEMENT_API_KEY", "")
    if base.endswith("/v1"):
        base = base[:-3].rstrip("/")
    if not base or not inference_key or not management_key:
        print("temporary_no_capacity: OmniRoute reconciliation credentials unavailable")
        return 2
    try:
        catalog = _get(f"{base}/models", inference_key)
        ranking = _get(ARENA_URL, "")
        models = qualified_models(catalog, ranking)
        combos = _get(f"{base}/api/combos", management_key).get("combos", [])
        selected_models = models or [NO_CAPACITY_MODEL]

        def put_combo(combo_id: str, payload: dict[str, Any]) -> None:
            request = urllib.request.Request(
                f"{base}/api/combos/{combo_id}", data=json.dumps(payload).encode(), method="PUT",
                headers={"Authorization": f"Bearer {management_key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30):
                pass

        def read_combos() -> list[dict[str, Any]]:
            return _get(f"{base}/api/combos", management_key).get("combos", [])

        ok, failures = reconcile_combos(combos, selected_models, put_combo, read_combos)
        if not ok:
            print("temporary_no_capacity: " + "; ".join(failures))
            return 5
        if not models:
            print("temporary_no_capacity: authoritative sources exposed no qualified model")
            return 3
        print(f"reconciled_qualified_models={len(models)}")
        return 0
    except (urllib.error.URLError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"temporary_no_capacity: reconciliation failed ({type(error).__name__})")
        return 4


if __name__ == "__main__":
    sys.exit(main())
