"""Pruned Python analytics routes stay absent; native Rust v2 is kept (#4861).

The Python ``/api/analytics/metrics`` and ``/api/v1/analytics/metrics``
handlers were deleted with their router mounts because no browser caller
remains — the JavaScript client calls the native Rust
``GET /api/v2/analytics/metrics`` resource (#4348). These guards assert the
pruned Python surface answers 404 and stays out of the generated OpenAPI
contract, while the retained eager health/ping/metrics routes keep working.
The analytics service/schema modules that the native resource depends on are
not removed by this PR and are covered by the native contract tests.
"""

import pytest
from httpx import AsyncClient

from app.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/analytics/metrics",
        "/api/v1/analytics/metrics",
    ],
)
async def test_pruned_python_analytics_returns_404(
    auth_client: AsyncClient, path: str
) -> None:
    """The deleted Python analytics handlers answer 404 on both aliases."""
    response = await auth_client.get(path)
    assert response.status_code == 404


def test_pruned_python_analytics_absent_from_openapi() -> None:
    """The pruned Python analytics paths stay out of the OpenAPI contract."""
    schema = create_app(serve_frontend=False).openapi()
    for path in ("/api/analytics/metrics", "/api/v1/analytics/metrics"):
        assert path not in schema["paths"], f"{path} must stay pruned"


@pytest.mark.asyncio
async def test_retained_metrics_surface_still_available(client: AsyncClient) -> None:
    """The eager ``/api/metrics`` surface is a different, retained route."""
    response = await client.get("/api/metrics")
    assert response.status_code == 200
