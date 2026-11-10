"""Pruned admin CSV import/export/delete routes stay absent (#4861).

The zero-browser admin surface (import/export CSV/JSON/summary and
delete-test-data) was deleted with its router mounts. These guards assert
every pruned admin path answers 404 on both the bare and ``/api/v1`` aliases
and stays out of the generated OpenAPI contract, while the retained eager
health/ping/metrics routes keep working. The underlying admin service helpers
remain for non-HTTP callers and are not exercised here.
"""

import pytest
from httpx import AsyncClient

from app.main import create_app

PRUNED_ADMIN_PATHS = (
    "/api/admin/import/csv/",
    "/api/v1/admin/import/csv/",
    "/api/admin/export/csv/",
    "/api/v1/admin/export/csv/",
    "/api/admin/export/json/",
    "/api/v1/admin/export/json/",
    "/api/admin/export/summary/",
    "/api/v1/admin/export/summary/",
    "/api/admin/delete-test-data/",
    "/api/v1/admin/delete-test-data/",
)


@pytest.mark.asyncio
async def test_pruned_admin_export_returns_404(auth_client: AsyncClient) -> None:
    """Every pruned admin GET export path answers 404."""
    for path in (
        "/api/admin/export/csv/",
        "/api/v1/admin/export/csv/",
        "/api/admin/export/json/",
        "/api/v1/admin/export/json/",
        "/api/admin/export/summary/",
        "/api/v1/admin/export/summary/",
    ):
        response = await auth_client.get(path)
        assert response.status_code == 404, f"{path} must stay pruned"


@pytest.mark.asyncio
async def test_pruned_admin_mutations_return_404(auth_client: AsyncClient) -> None:
    """Every pruned admin POST mutation path answers 404."""
    for path in (
        "/api/admin/import/csv/",
        "/api/v1/admin/import/csv/",
        "/api/admin/delete-test-data/",
        "/api/v1/admin/delete-test-data/",
    ):
        response = await auth_client.post(path)
        assert response.status_code == 404, f"{path} must stay pruned"


def test_pruned_admin_absent_from_openapi() -> None:
    """The pruned admin paths stay out of the generated OpenAPI contract."""
    schema = create_app(serve_frontend=False).openapi()
    for path in PRUNED_ADMIN_PATHS:
        assert path not in schema["paths"], f"{path} must stay pruned"
