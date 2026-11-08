"""Pruned crossover-template handlers: the browser never calls them."""

import pytest
from httpx import AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_crossover_template_handlers_are_absent(auth_client: AsyncClient) -> None:
    """Both crossover adopt/preview handlers are gone."""
    assert (await auth_client.post("/api/v1/crossover-templates/preview", json={})).status_code == 404
    assert (await auth_client.post("/api/v1/crossover-templates/adopt", json={})).status_code == 404
    schema = create_app(serve_frontend=False).openapi()
    assert "/api/v1/crossover-templates/preview" not in schema["paths"]
    assert "/api/v1/crossover-templates/adopt" not in schema["paths"]
