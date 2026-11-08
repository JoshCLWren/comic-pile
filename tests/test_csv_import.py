"""Pruned admin CSV handlers: export/import are gone."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_admin_csv_handlers_are_absent(auth_client: AsyncClient) -> None:
    """Admin CSV endpoints on both prefixes are gone."""
    assert (await auth_client.get("/api/v1/admin/export/csv/")).status_code == 404
    assert (await auth_client.post("/api/v1/admin/import/csv/")).status_code == 404
