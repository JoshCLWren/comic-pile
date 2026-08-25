"""Regression coverage for canonical analytics API versioning."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_analytics_v1_matches_legacy_alias(auth_client: AsyncClient) -> None:
    """Canonical analytics output must match the retained legacy alias."""
    canonical = await auth_client.get("/api/v1/analytics/metrics")
    legacy = await auth_client.get("/api/analytics/metrics")

    assert canonical.status_code == legacy.status_code == 200
    assert canonical.json() == legacy.json()
