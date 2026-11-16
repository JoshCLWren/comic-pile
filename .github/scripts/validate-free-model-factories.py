#!/usr/bin/env python3
"""Validate model-agnostic factory discovery and provider-derived worker identity.

No test or contract assumes a particular published model ID or worker roster.
Execution availability is proved only by a real worker run, not this validator.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_dispatch_credential_filter import filter_workers, worker_sources
from factory_provider_candidates import discover
from factory_provider_registry import PROVIDERS
from factory_worker_slots import resolve, slot_count, slots, sources

WORKFLOWS = ROOT / ".github" / "workflows"


def validate() -> None:
    source_names = sources()
    capacity = slot_count({"FACTORY_SLOTS_PER_PROVIDER": "2"})
    assert capacity == 2
    derived = slots({"FACTORY_SLOTS_PER_PROVIDER": "2"})
    assert len(derived) == capacity * len(source_names)
    assert len({item.worker for item in derived}) == len(derived)
    assert set(item.source for item in derived) == set(source_names)
    assert all("model" not in item.as_record() for item in derived)
    assert all(resolve(item.worker, {"FACTORY_SLOTS_PER_PROVIDER": "2"}) == item for item in derived)
    synthetic = {"data": [
        {"id": "synthetic/paid-model", "pricing": {"prompt": "2", "completion": "4"}},
        {"id": "synthetic/unpriced-model"},
    ]}
    for source in PROVIDERS:
        result = discover(source, json.dumps(synthetic))
        assert result.status == "available", source
        assert {row.model for row in result.candidates} == {
            "synthetic/paid-model", "synthetic/unpriced-model",
        }, source
        provider = PROVIDERS[source].provider
        assert all(
            candidate.runtime_model == f"{provider}/{candidate.model}"
            for candidate in result.candidates
        )
    assert discover("opencode-free", "opencode/synthetic-model\n").candidates
    assert not discover("opencode-free", "other/synthetic-model\n").candidates
    assert worker_sources()
    some_source = next(iter(PROVIDERS))
    some_worker = next(item.worker for item in slots() if item.source == some_source)
    kept, deferred = filter_workers([some_worker], worker_sources(), {})
    assert kept == [] and len(deferred) == 1

    dispatch = (WORKFLOWS / "fixed-model-factory-dispatch.yml").read_text(encoding="utf-8")
    runner = (WORKFLOWS / "free-model-factory-run.yml").read_text(encoding="utf-8")
    entry = (WORKFLOWS / "free-model-factory-entry.yml").read_text(encoding="utf-8")
    assert 'factory_worker_slots.py" offer' in dispatch
    assert "factory_dispatch_credential_filter.py filter" in dispatch
    assert 'assign --worker "$worker"' in dispatch
    assert dispatch.index("factory_dispatch_credential_filter.py filter") < dispatch.index(
        'assign --worker "$worker"'
    )
    assert 'factory_worker_slots.py resolve' in runner
    assert "factory_runtime_model_select.py" in runner
    assert "factory_published_model_catalog.py" in runner
    assert "factory_live_opencode.py" in runner
    assert "factory_kilo_catalog.py" in runner
    assert "Require Vercel model to remain zero-price" not in runner
    assert "selected-from-live-runtime-catalog" in runner
    assert "group: fixed-model-factory-${{ inputs.worker }}" in runner
    assert "cancel-in-progress: false" in runner
    assert "uses: ./.github/workflows/free-model-factory-run.yml" in entry
    assert "secrets: inherit" in entry

    registry = (ROOT / ".github/scripts/factory_provider_registry.py").read_text(encoding="utf-8")
    assert "explicit_models" not in registry
    print(
        json.dumps({
            "providers": len(source_names),
            "registered_catalog_providers": len(PROVIDERS),
            "synthetic_workers_validated": len(derived),
            "runtime_model_inventory_pinned": False,
        }, sort_keys=True)
    )


if __name__ == "__main__":
    validate()
