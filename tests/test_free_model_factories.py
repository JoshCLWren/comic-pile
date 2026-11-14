"""Roster contracts that survive adding, retiring, and renumbering factories."""

import json
from collections import defaultdict
from pathlib import Path


def _roster() -> list[list[str]]:
    return [
        line.split("\t")
        for line in Path(".github/free-model-factories.tsv").read_text().splitlines()
        if line and not line.startswith("#")
    ]


def _lock() -> dict:
    return json.loads(Path(".github/factory-expected-workers.json").read_text())


def test_retired_worker_ids_never_overlap_current_workers() -> None:
    """Retirement is durable and current IDs match the generated lock."""
    rows = _roster()
    lock = _lock()
    active = {int(row[0]) for row in rows}
    assert len(rows) == len(active)
    assert active == set(lock["expected_workers"])
    assert active.isdisjoint(lock["retired_workers"])
    assert "mistral-small" not in {row[2] for row in rows}


def test_duplicate_free_routes_stagger_without_requiring_fixed_worker_ids() -> None:
    """Duplicate route workers must not all contend at the same minute."""
    routes: dict[tuple[str, str], list[int]] = defaultdict(list)
    for worker, source, model, minute, *_ in _roster():
        routes[(source, model)].append(int(minute))
    for source, model in (("z-ai", "glm-4.5-flash"), ("kilo-auto", "kilo-auto/free")):
        minutes = routes[(source, model)]
        if len(minutes) > 1:
            assert len(set(minutes)) == len(minutes)
            assert all(minute in range(0, 60, 5) for minute in minutes)
    workflow = Path(".github/workflows/free-model-factory-run.yml").read_text()
    smoke = workflow.split("- name: Smoke Kilo Auto Free through Kilo CLI")[1].split("\n      - name:")[0]
    assert smoke.index("grep -q '^provider_quota'") < smoke.index("if grep -q 'KILO_AUTO_FREE_OK'")


def test_openrouter_coding_options_are_model_scoped_not_worker_scoped() -> None:
    """New free models can come and go without invalidating old worker assertions."""
    rows = _roster()
    lock = _lock()
    models = {row[2] for row in rows}
    retired = set(lock["retired_models"])
    for model in (
        "thinkingmachines/inkling-2-small:free",
        "baidu/ernie-5.5-flash-preview:free",
        "inclusionai/ling-3.2-flash:free",
    ):
        assert (model in models) != (model in retired)
        if model in models:
            assert any(row[1] == "openrouter-free" and row[2] == model for row in rows)
    for model in ("thinkingmachines/inkling:free", "thinkingmachines/inkling-small:free"):
        assert model in retired
        assert model not in models
