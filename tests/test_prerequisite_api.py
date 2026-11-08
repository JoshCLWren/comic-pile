"""Pruned prerequisite handlers: the browser never calls them."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_prerequisite_handlers_are_absent(auth_client: AsyncClient) -> None:
    """All prerequisite HTTP handlers are gone."""
    assert (await auth_client.get("/api/v1/prerequisites/")).status_code == 404
    assert (await auth_client.post("/api/v1/prerequisites/", json={})).status_code == 404
