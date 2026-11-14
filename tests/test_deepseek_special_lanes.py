"""Regression checks for retirement of the failed DeepSeek Free experiment."""

import json
from pathlib import Path


def test_failed_deepseek_experiment_is_not_scheduled() -> None:
    """A locked-out free model never reenters through a different worker ID."""
    roster = Path(".github/free-model-factories.tsv").read_text()
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    active_models = {
        line.split("\t")[2] for line in roster.splitlines()
        if line and not line.startswith("#")
    }
    assert "deepseek-v4.1-flash-free" in lock["retired_models"]
    assert "deepseek-v4.1-flash-free" not in active_models
    assert set(lock["retired_workers"]).isdisjoint(lock["expected_workers"])


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
