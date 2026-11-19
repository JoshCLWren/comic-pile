"""Tests for process-local per-route traffic counters used by request logging."""

from collections.abc import Iterator

import pytest

from app.traffic_metrics import (
    _MAX_TRACKED_KEYS,
    get_traffic_instance_id,
    record_route_hit,
    reset_traffic_counters_for_tests,
    resolve_route_template,
    traffic_snapshot,
)


@pytest.fixture(autouse=True)
def clean_counters() -> Iterator[None]:
    """Isolate counter state between tests."""
    reset_traffic_counters_for_tests()
    yield
    reset_traffic_counters_for_tests()




def test_snapshot_is_deterministically_sorted() -> None:
    """Counter entries come back sorted so collectors can diff snapshots."""
    record_route_hit("POST", "/api/v1/b", 200)
    record_route_hit("GET", "/api/v1/c", 500)
    record_route_hit("GET", "/api/v1/a", 200)

    counters = traffic_snapshot().counters
    keys = [(counter.method, counter.route) for counter in counters]
    assert keys == sorted(keys)


def test_snapshot_carries_instance_id() -> None:
    """Snapshots expose the stable process identifier for fleet aggregation."""
    assert traffic_snapshot().instance_id == get_traffic_instance_id()




def test_resolve_route_template_falls_back_when_unmatched() -> None:
    """Requests that never matched a route collapse into one bucket."""
    assert resolve_route_template({}) == "__unmatched__"


def test_resolve_route_template_ignores_templates_without_path() -> None:
    """Route objects without a usable path fall back to the unmatched bucket."""
    assert resolve_route_template({"route": object()}) == "__unmatched__"


def test_counter_keys_are_capped_against_cardinality_explosion() -> None:
    """Pathological key growth folds into an overflow bucket instead of leaking memory."""
    for index in range(_MAX_TRACKED_KEYS + 25):
        record_route_hit("GET", f"/unmatched/{index}", 200)

    snapshot = traffic_snapshot()
    routes = {counter.route for counter in snapshot.counters}
    overflow = [counter for counter in snapshot.counters if counter.route == "__overflow__"]
    assert len(routes) <= _MAX_TRACKED_KEYS + 1
    assert len(overflow) == 1
    assert overflow[0].count == 25


