"""Pruned correction-examples handler: the browser never calls it."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_correction_examples_handler_is_absent(auth_client: AsyncClient) -> None:
    """The v1 correction-examples endpoint is gone."""
    assert (await auth_client.get("/api/v1/sessions/correction-examples")).status_code == 404
