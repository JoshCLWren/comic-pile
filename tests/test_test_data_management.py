"""Pruned admin handlers: CSV export/import and test-data endpoints are gone."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_admin_handlers_are_absent(auth_client: AsyncClient) -> None:
    """Both admin twins are gone."""
    assert (await auth_client.get("/api/v1/admin/export/csv/")).status_code == 404
    assert (await auth_client.get("/api/admin/export/csv/")).status_code == 404
    assert (await auth_client.post("/api/v1/admin/delete-test-data/")).status_code == 404
