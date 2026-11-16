"""Per-lease model failover exhausts discovered candidates without a roster."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github/scripts"))

from factory_model_failover import ExhaustedCandidates, select_next  # noqa: E402


def _catalog(*models: str) -> dict:
    return {"data": [{"id": model, "supported_parameters": ["tools"]} for model in models]}


def test_openrouter_free_iterates_every_discovered_free_candidate() -> None:
    names = [f"sample/generated-{i}:free" for i in range(8)]
    catalog = _catalog("sample/paid", *names)
    attempted: set[str] = set()
    for _ in names:
        selected = select_next("openrouter-free", "12345", attempted, {}, catalog_json=catalog)
        model = selected["model"]
        assert model in names and model not in attempted
        assert selected["runtime_model"] == f"openrouter/{model}"
        attempted.add(model)
    assert attempted == set(names)
    with pytest.raises(ExhaustedCandidates):
        select_next("openrouter-free", "12345", attempted, {}, catalog_json=catalog)


def test_cooldown_is_exact_model_and_provider() -> None:
    candidates = [f"sample/model-{i}" for i in range(5)]
    catalog = _catalog(*candidates)
    excluded = {"nvidia": [candidates[0]], "requesty": [candidates[1]]}
    attempted: set[str] = set()
    for _ in range(len(candidates) - 1):
        selected = select_next("nvidia", "567", attempted, excluded, catalog_json=catalog)
        assert selected["model"] not in attempted
        assert selected["model"] != candidates[0]
        attempted.add(selected["model"])
    assert attempted == set(candidates[1:])
    with pytest.raises(ExhaustedCandidates):
        select_next("nvidia", "567", attempted, excluded, catalog_json=catalog)
    # A source/model failure must not suppress the same model on another source.
    other = select_next("requesty", "567", set(), excluded, catalog_json=catalog)
    assert other["model"] != candidates[1]
    assert other["model"] in candidates


def test_opencode_free_iterates_live_catalog_without_roster() -> None:
    names = [f"test-generated-{i}" for i in range(4)]
    catalog = json.dumps({"models": [{"id": name, "cost": {"input": 0, "output": 0}}
                                      for name in names]})
    attempted: set[str] = set()
    for _ in names:
        selected = select_next("opencode-free", "41", attempted, {}, catalog_text=catalog)
        assert selected["model"] in names
        assert selected["model"] not in attempted
        attempted.add(selected["model"])
    with pytest.raises(ExhaustedCandidates):
        select_next("opencode-free", "41", attempted, {}, catalog_text=catalog)


def test_kilo_tries_all_published_cli_selectors() -> None:
    names = [f"kilo-auto/generated-{i}" for i in range(3)]
    catalog = "\n".join(names)
    attempted: set[str] = set()
    for _ in names:
        selected = select_next("kilo-auto", "41", attempted, {}, catalog_text=catalog)
        assert selected["model"] == selected["runtime_model"]
        assert selected["model"] not in attempted
        attempted.add(selected["model"])
    with pytest.raises(ExhaustedCandidates):
        select_next("kilo-auto", "41", attempted, {}, catalog_text=catalog)


def test_excluded_models_never_appear_even_if_unattempted() -> None:
    catalog = _catalog("generated/a:free", "generated/b:free", "generated/c:free")
    selection = select_next(
        "openrouter-free", "99", set(),
        {"openrouter-free": ["generated/a:free", "generated/b:free"]},
        catalog_json=catalog,
    )
    assert selection["model"] == "generated/c:free"
