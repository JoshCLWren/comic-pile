"""Tests for the free-model factory's explicit retirement policy."""

import json
from pathlib import Path


def test_unusable_models_are_locked_out_of_the_factory_roster() -> None:
    """Retirement removes scheduling capacity without erasing historical evidence."""
    roster = Path(".github/free-model-factories.tsv").read_text()
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    retired = {48, 55, 74, 87, 88, 89, 90}
    assert retired.isdisjoint(lock["expected_workers"])
    assert retired.issubset(lock["retired_workers"])
    assert {"codestral-latest", "nemotron-3-nano:30b", "deepseek-v4.1-flash-free"}.issubset(lock["retired_models"])
    active = {int(line.split("\t", 1)[0]) for line in roster.splitlines()
              if line and not line.startswith("#")}
    assert retired.isdisjoint(active)
    assert "mistral-small" not in roster
