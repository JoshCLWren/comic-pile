"""Tests for privacy-safe cache command-count instrumentation."""

import pytest

from app.cache_metrics import CacheCommandMetrics


def test_records_aggregate_command_counts() -> None:
    metrics = CacheCommandMetrics()

    metrics.record("GET")
    metrics.record("get", count=2)
    metrics.record("delete")

    assert metrics.snapshot() == {"get": 3, "delete": 1}
    assert metrics.total() == 4


def test_snapshot_is_detached_from_internal_state() -> None:
    metrics = CacheCommandMetrics()
    metrics.record("set")

    snapshot = metrics.snapshot()
    snapshot["set"] = 99

    assert metrics.snapshot() == {"set": 1}


@pytest.mark.parametrize(("command", "count"), [("", 1), ("   ", 1), ("get", 0), ("get", -1)])
def test_rejects_invalid_metric_records(command: str, count: int) -> None:
    metrics = CacheCommandMetrics()

    with pytest.raises(ValueError):
        metrics.record(command, count=count)


def test_reset_clears_all_counts() -> None:
    metrics = CacheCommandMetrics()
    metrics.record("get")
    metrics.record("set")

    metrics.reset()

    assert metrics.snapshot() == {}
    assert metrics.total() == 0
