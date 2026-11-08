"""Regression coverage for pruned analytics handlers."""

import pytest
from httpx import AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_analytics_v1_matches_legacy_alias(auth_client: AsyncClient) -> None:
    """Python analytics handlers were pruned; neither twin exists."""
    canonical = await auth_client.get("/api/v1/analytics/metrics")
    legacy = await auth_client.get("/api/analytics/metrics")

    assert canonical.status_code == 404
    assert legacy.status_code == 404


@pytest.mark.asyncio
async def test_analytics_metrics_contract_is_typed_and_stable(
    auth_client: AsyncClient,
) -> None:
    """The v2 native metrics resource is the only metrics API; v1 is gone."""
    response = await auth_client.get("/api/v1/analytics/metrics")
    assert response.status_code == 404

    schema = create_app(serve_frontend=False).openapi()
    assert "/api/v1/analytics/metrics" not in schema["paths"]
