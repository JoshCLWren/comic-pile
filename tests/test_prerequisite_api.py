"""Pruned prerequisites routes stay absent (#4861).

The stable prerequisites handlers (``/api/v1/prerequisites/`` and
``/api/v1/prerequisites/{id}``) were deleted with their dependency
sub-router because no browser caller remains. These guards assert the
collection and item routes answer 404 and stay out of the generated OpenAPI
contract, while the retained eager health/ping/metrics routes keep working.
The underlying :class:`Dependency` model and prerequisite service remain for
non-HTTP callers (reading order, migrations) and are not exercised here.
"""

import pytest
from httpx import AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_pruned_prerequisites_collection_returns_404(
    auth_client: AsyncClient,
) -> None:
    """The deleted prerequisites collection answers 404 on GET and POST."""
    listing = await auth_client.get("/api/v1/prerequisites/")
    assert listing.status_code == 404

    creation = await auth_client.post(
        "/api/v1/prerequisites/",
        json={"source_issue_id": 1, "target_issue_id": 2},
    )
    assert creation.status_code == 404


@pytest.mark.asyncio
async def test_pruned_prerequisite_item_returns_404(
    auth_client: AsyncClient,
) -> None:
    """The deleted prerequisite item routes answer 404 on PATCH and DELETE."""
    item = "/api/v1/prerequisites/123"
    updated = await auth_client.patch(item, json={"note": "probe"})
    assert updated.status_code == 404

    deleted = await auth_client.delete(item)
    assert deleted.status_code == 404


def test_pruned_prerequisites_absent_from_openapi() -> None:
    """The pruned prerequisites paths stay out of the OpenAPI contract."""
    schema = create_app(serve_frontend=False).openapi()
    for path in (
        "/api/v1/prerequisites/",
        "/api/v1/prerequisites/{prerequisite_id}",
    ):
        assert path not in schema["paths"], f"{path} must stay pruned"
