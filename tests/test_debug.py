"""Pruned debug log handlers: non-production tooling, zero browser use."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_debug_handlers_are_absent(client: AsyncClient) -> None:
    """Both debug log twins are gone."""
    assert (await client.post("/api/debug/log", json={"level": "INFO", "message": "x"})).status_code == 404
    assert (await client.post("/api/v1/debug/log", json={"level": "INFO", "message": "x"})).status_code == 404
