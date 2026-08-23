"""Tests for process-local per-route traffic counters and their snapshot API."""

from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.schemas.traffic_metrics import TrafficMetricsSnapshot
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


def test_record_route_hit_aggregates_counts_per_key() -> None:
    """Repeated hits on the same key accumulate into a single tally."""
    record_route_hit("GET", "/api/v1/threads", 200)
    record_route_hit("GET", "/api/v1/threads", 200)
    record_route_hit("GET", "/api/v1/threads", 404)

    counted = {
        (counter.method, counter.route, counter.status_class): counter.count
        for counter in traffic_snapshot().counters
    }
    assert counted[("GET", "/api/v1/threads", "2xx")] == 2
    assert counted[("GET", "/api/v1/threads", "4xx")] == 1


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


def test_resolve_route_template_uses_scope_template() -> None:
    """A matched route resolves to its path template, not the raw path."""

    class _FakeRoute:
        path = "/api/v1/threads/{thread_id}"

    assert resolve_route_template({"route": _FakeRoute()}) == "/api/v1/threads/{thread_id}"


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


async def test_traffic_endpoint_requires_authentication(client: AsyncClient) -> None:
    """Unauthenticated callers must not read traffic aggregates."""
    response = await client.get("/api/v1/traffic-metrics")
    assert response.status_code == 401


async def test_traffic_endpoint_reports_route_counters(auth_client: AsyncClient) -> None:
    """Authenticated callers see counters for previously completed requests."""
    listed = await auth_client.get("/api/v1/threads/")
    assert listed.status_code in (200, 404)

    # The snapshot cannot contain its own request: middleware records each
    # hit only after the response completes. Assert on the earlier call.
    response = await auth_client.get("/api/v1/traffic-metrics")
    assert response.status_code == 200

    payload = TrafficMetricsSnapshot.model_validate(response.json())
    assert payload.instance_id == get_traffic_instance_id()
    counted = {
        (counter.method, counter.route, counter.status_class): counter.count
        for counter in payload.counters
    }
    assert counted[("GET", "/api/v1/threads/", "2xx")] == 1


async def test_unmatched_api_paths_collapse_into_catch_all_template(
    auth_client: AsyncClient,
) -> None:
    """Unknown API paths record under the registered catch-all template."""
    missing = await auth_client.get("/api/v1/does-not-exist")
    assert missing.status_code == 404

    response = await auth_client.get("/api/v1/traffic-metrics")
    assert response.status_code == 200

    payload = TrafficMetricsSnapshot.model_validate(response.json())
    catch_all_404 = [
        counter
        for counter in payload.counters
        if counter.route == "/api/{path:path}" and counter.status_class == "4xx"
    ]
    assert len(catch_all_404) == 1
    assert catch_all_404[0].count >= 1
