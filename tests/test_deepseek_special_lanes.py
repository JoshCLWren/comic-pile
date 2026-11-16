"""Retired experiment worker pins cannot become active dynamic provider slots."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github/scripts"))
SLOTS = importlib.import_module("factory_worker_slots")


def test_provider_slots_do_not_pin_retired_experiment_models() -> None:
    """Provider-derived slots must not preserve retired experiment model pins."""
    dynamic = SLOTS.slots({"FACTORY_SLOTS_PER_PROVIDER": "2"})
    assert dynamic
    assert all("model" not in slot.as_record() for slot in dynamic)
    assert all(int(slot.worker) > 1_000_000_000 for slot in dynamic)


def test_old_manual_comparison_does_not_schedule_a_model_worker() -> None:
    """Manual comparison workflows must not register scheduled factory workers."""
    # The worker-74 pinned DeepSeek smoke was removed with the TSV roster.
    assert not (ROOT / ".github/workflows/opencode-deepseek-free-smoke.yml").exists()
    for filename in ("deepseek-free-auth-comparison.yml",):
        workflow = (ROOT / ".github/workflows" / filename).read_text()
        assert "  schedule:" not in workflow
        assert "  pull_request:" not in workflow
