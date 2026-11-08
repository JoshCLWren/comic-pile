"""Pruned collection-exclusion handlers: the browser never calls them."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_collection_exclusion_handlers_are_absent(auth_client: AsyncClient) -> None:
    """All collection-exclusion HTTP handlers are gone."""
    assert (await auth_client.get("/api/v1/collection-exclusions")).status_code == 404
    assert (await auth_client.post("/api/v1/collection-exclusions", json={})).status_code == 404
