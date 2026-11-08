"""Pruned analytics handlers: the browser never calls them.

The Python analytics metrics handlers were deleted in the zero-browser sweep.
The browser calls the native v2 resource; both Python twins must 404.
"""

import pytest
from httpx import AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_analytics_handlers_are_absent(auth_client: AsyncClient) -> None:
    """Both Python analytics twins are gone."""
    assert (await auth_client.get("/api/v1/analytics/metrics")).status_code == 404
    assert (await auth_client.get("/api/analytics/metrics")).status_code == 404
    schema = create_app(serve_frontend=False).openapi()
    assert "/api/v1/analytics/metrics" not in schema["paths"]
