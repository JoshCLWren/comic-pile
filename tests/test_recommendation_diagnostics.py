"""Pruned recommendation-diagnostics route stays absent (#4861).

The HTTP handler ``GET /api/v1/recommendations/diagnostics`` was deleted
with its deferred mount because no browser caller remains. These guards
assert the diagnostics path answers 404 and stays out of the generated
OpenAPI contract, while the retained eager health/ping/metrics routes keep
working. The diagnostics service
(:func:`app.services.recommendation_diagnostics.compute_recommendation_diagnostics`)
and its schema remain for non-HTTP callers and are covered at the service
level by the adaptive Roll acceptance tests instead of through HTTP.
"""

import pytest
from httpx import AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_pruned_diagnostics_returns_404(auth_client: AsyncClient) -> None:
    """The deleted diagnostics handler answers 404 for authenticated callers."""
    response = await auth_client.get("/api/v1/recommendations/diagnostics")
    assert response.status_code == 404


def test_pruned_diagnostics_absent_from_openapi() -> None:
    """The pruned diagnostics path stays out of the generated OpenAPI contract."""
    schema = create_app(serve_frontend=False).openapi()
    assert "/api/v1/recommendations/diagnostics" not in schema["paths"], (
        "/api/v1/recommendations/diagnostics must stay pruned"
    )


@pytest.mark.asyncio
async def test_retained_ping_still_available(client: AsyncClient) -> None:
    """The eager ``/api/ping`` heartbeat route is retained and unaffected."""
    response = await client.get("/api/ping")
    assert response.status_code == 200
