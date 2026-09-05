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
MAX_AGE_SECONDS = 7 * 24 * 60 * 60
CASCADE_NAMES = ("free-cascade-small", "free-cascade-big")


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
    """Return live free tool-capable models with exact fresh Arena identities."""
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
        if not model.endswith(":free") or not isinstance(capabilities, dict):
            continue
        if capabilities.get("tool_calling") is not True or _key(model) not in scores:
            continue
        qualified.append(model)
    return sorted(set(qualified), key=lambda model: (-scores[_key(model)], model))


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
        if not models:
            print("temporary_no_capacity: no exact ranked free tool-capable model")
            return 3
        combos = _get(f"{base}/api/combos", management_key).get("combos", [])
        for combo in combos:
            if combo.get("name") not in CASCADE_NAMES:
                continue
            payload = {
                "strategy": "priority",
                "models": [
                    {"kind": "model", "model": model, "providerId": "openrouter", "weight": 0}
                    for model in models
                ],
                "config": combo.get("config") or {},
            }
            request = urllib.request.Request(
                f"{base}/api/combos/{combo['id']}",
                data=json.dumps(payload).encode(),
                method="PUT",
                headers={
                    "Authorization": f"Bearer {management_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=30):
                pass
        print(f"reconciled_qualified_models={len(models)}")
        return 0
    except (urllib.error.URLError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"temporary_no_capacity: reconciliation failed ({type(error).__name__})")
        return 4


if __name__ == "__main__":
    sys.exit(main())
