"""Pruned CBL collection-exclusion handlers: the browser never calls them."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_cbl_collection_handlers_are_absent(auth_client: AsyncClient) -> None:
    """Collection-exclusion endpoints on CBL surface are gone."""
    assert (await auth_client.get("/api/v1/collection-exclusions")).status_code == 404
