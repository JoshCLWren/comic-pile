"""Factory catalog slots have durable identities and no hardcoded upstream IDs."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github/scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ROSTER = _load("factory_roster")
RETIRE = _load("factory_model_retirement")
STATE = _load("factory_state_operations")

CATALOG_SOURCES = ROSTER.CATALOG_MODEL_SOURCES


def test_manifest_and_snapshot_do_not_pin_catalog_models() -> None:
    rows = ROSTER.load_roster_rows()
    lock = ROSTER.load_roster_lock()
    snapshot = ROSTER.load_roster_snapshot()
    catalog_slots = [row for row in rows if row["source"] in CATALOG_SOURCES]
    assert catalog_slots  # Worker count may grow or shrink through approved policy.
    assert all(row["model"] == ROSTER.CATALOG_MODEL_SLOT for row in catalog_slots)
    assert all("catalog slot" in row["display_name"] for row in catalog_slots)
    assert set(lock["expected_workers"]) == ROSTER.roster_worker_ids(rows)
    assert ROSTER.build_roster_snapshot(rows, lock) == snapshot
    assert json.loads(Path(".github/factory-expected-workers.json").read_text())["model_binding"] == "catalog-backed"


@pytest.mark.parametrize("source", sorted(CATALOG_SOURCES))
def test_model_discovery_cannot_retire_a_dynamic_worker(source: str) -> None:
    row = {
        "worker": "999",
        "source": source,
        "model": ROSTER.CATALOG_MODEL_SLOT,
        "minute": "0",
        "scheduler": "dispatcher",
        "display_name": "catalog",
    }
    decision = RETIRE.decide_pin(row, {}, {ROSTER.CATALOG_MODEL_SLOT})
    assert decision.action == "keep"
    assert "catalog" in decision.reason


def test_worker_fibonacci_backoff_survives_model_rotation() -> None:
    now = datetime.now(UTC)
    cooldown = (now + timedelta(minutes=15)).isoformat()
    record = {
        "payload": [{
            "source": "openrouter-free",
            "model": "model-a:free",
            "streak": 4,
            "next_retry_at": cooldown,
            "suspended": False,
        }],
        "expires_at": now + timedelta(days=90),
    }
    reason = STATE.worker_backoff_reason(
        record, "openrouter-free", ROSTER.CATALOG_MODEL_SLOT, now,
    )
    assert reason is not None and "Fibonacci" in reason
    assert STATE.worker_backoff_reason(record, "openrouter-free", "model-b:free", now) is None
    assert STATE.worker_backoff_reason(record, "vercel-ai-gateway", ROSTER.CATALOG_MODEL_SLOT, now) is None


def test_workflow_resolves_model_before_actual_inference() -> None:
    workflow = (ROOT / ".github/workflows/free-model-factory-run.yml").read_text()
    assert "factory_published_model_catalog.py" in workflow
    assert "factory_live_opencode.py" in workflow
    assert "runtime_model=vercel/$model" in workflow
    assert "runtime_model=openrouter/$model" in workflow
    assert "steps.model_preflight.outputs.model" in workflow


def test_historical_worker_streak_spans_catalog_model_rotations() -> None:
    def event(run_id: int, model: str, kind: str = "worker_failed") -> dict:
        return {
            "event_type": kind,
            "detail": {
                "run_id": str(run_id), "source": "openrouter-free",
                "model": model, "outcome_class": "provider_failure",
                "configured": True,
            },
        }

    events = [
        event(43, "model-b:free"),
        event(42, "model-a:free"),
        event(41, "model-c:free"),
    ]
    assert STATE.historical_failure_streak(
        events, 44, "openrouter-free", "model-b:free",
        model_only=False, model_independent=True,
    ) == 3
    assert STATE.historical_failure_streak(
        events, 44, "openrouter-free", "model-b:free",
        model_only=False, model_independent=False,
    ) == 1
    assert STATE.historical_failure_streak(
        events, 44, "openrouter-free", "model-b:free",
        model_only=True,
    ) == 1
