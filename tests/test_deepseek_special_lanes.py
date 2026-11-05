"""Regression checks for retirement of the failed DeepSeek Free experiment."""

import json
from pathlib import Path


def test_deepseek_experimental_worker_slots_are_retired() -> None:
    """None of the special pinned slots can enter the dispatcher roster."""
    roster = Path(".github/free-model-factories.tsv").read_text()
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    retired = {74, 87, 88, 89, 90}
    active = {int(line.split("\t", 1)[0]) for line in roster.splitlines()
              if line and not line.startswith("#")}
    assert retired.isdisjoint(active)
    assert retired.isdisjoint(lock["expected_workers"])
    assert retired.issubset(lock["retired_workers"])
    assert "deepseek-v4.1-flash-free" in lock["retired_models"]


def test_deepseek_comparison_is_manual_only() -> None:
    """No scheduled or PR-triggered probes run for the retired experiment."""
    comparison = Path(".github/workflows/deepseek-free-auth-comparison.yml").read_text()
    assert "  workflow_dispatch:" in comparison
    assert "  schedule:" not in comparison
    assert "  pull_request:" not in comparison
    smoke = Path(".github/workflows/opencode-deepseek-free-smoke.yml").read_text()
    assert "  workflow_dispatch:" in smoke
    assert "  schedule:" not in smoke
    assert "  pull_request:" not in smoke
