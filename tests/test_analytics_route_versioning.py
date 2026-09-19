"""Regression coverage for canonical analytics API versioning."""

import pytest
from httpx import AsyncClient

EXPECTED_METRICS_FIELDS = {
    "total_threads",
    "active_threads",
    "completed_threads",
    "completion_rate",
    "average_session_hours",
    "recent_sessions",
    "event_stats",
    "top_rated_threads",
}


@pytest.mark.asyncio
async def test_analytics_v1_matches_legacy_alias(auth_client: AsyncClient) -> None:
    """Canonical analytics output must match the retained legacy alias."""
    canonical = await auth_client.get("/api/v1/analytics/metrics")
    legacy = await auth_client.get("/api/analytics/metrics")

    assert canonical.status_code == legacy.status_code == 200
    assert canonical.json() == legacy.json()


@pytest.mark.asyncio
async def test_analytics_metrics_contract_is_typed_and_stable(
    auth_client: AsyncClient,
) -> None:
    """The metrics payload keeps the documented typed field contract."""
    response = await auth_client.get("/api/v1/analytics/metrics")
    assert response.status_code == 200

    payload = response.json()
    assert set(payload) == EXPECTED_METRICS_FIELDS
    assert isinstance(payload["total_threads"], int)
    assert isinstance(payload["active_threads"], int)
    assert isinstance(payload["completed_threads"], int)
    assert isinstance(payload["event_stats"], dict)
    assert isinstance(payload["recent_sessions"], list)
    assert isinstance(payload["top_rated_threads"], list)
