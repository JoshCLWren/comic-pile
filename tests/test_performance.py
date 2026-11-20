"""Tests for performance telemetry middleware and metrics endpoint."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.startup_diagnostics import reset_startup_diagnostics_for_test


@pytest.fixture()
async def client() -> AsyncIterator[AsyncClient]:
    """Create a fresh application client with reset startup diagnostics.

    Args:
        None.

    Returns:
        AsyncClient bound to a freshly created application instance.
    """
    reset_startup_diagnostics_for_test()
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.mark.asyncio
async def test_response_time_header(client: AsyncClient) -> None:
    """Verify X-Response-Time and X-Server-Cold-Start headers are set.

    Args:
        client: Fresh application test client.

    Returns:
        None.
    """
    response = await client.get("/health")
    assert response.status_code == 200
    assert "X-Response-Time" in response.headers
    assert response.headers.get("X-Server-Cold-Start") == "true"

    response2 = await client.get("/health")
    assert response2.headers.get("X-Server-Cold-Start") == "false"


@pytest.mark.asyncio
async def test_metrics_endpoint(client: AsyncClient) -> None:
    """Verify the /api/metrics endpoint returns startup_time and startup_duration.

    Args:
        client: Fresh application test client.

    Returns:
        None.
    """
    response = await client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "startup_time" in data
    assert "startup_duration" in data
    assert isinstance(data["startup_time"], float)
    assert isinstance(data["startup_duration"], float) or data["startup_duration"] is None


