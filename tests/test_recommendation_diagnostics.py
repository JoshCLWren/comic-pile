"""Pruned recommendation diagnostics: the browser never calls it."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_diagnostics_handler_is_absent(auth_client: AsyncClient) -> None:
    """The diagnostics endpoint is gone on the v1 prefix."""
    assert (await auth_client.get("/api/v1/recommendations/diagnostics")).status_code == 404
