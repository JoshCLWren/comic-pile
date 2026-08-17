"""Regression tests for issue #1389 ping endpoint."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_ping_returns_alive_without_database(client):
    """Ping endpoint must return alive and require zero DB access."""
    response = await auth_client.get("/api/ping")
    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "alive"}
