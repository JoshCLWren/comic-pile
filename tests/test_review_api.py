"""Removal-contract tests for the retired Reviews API."""

import re

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/reviews/"),
        ("POST", "/api/v1/reviews/"),
        ("GET", "/api/v1/reviews/1"),
        ("PUT", "/api/v1/reviews/1"),
        ("PATCH", "/api/v1/reviews/1"),
        ("DELETE", "/api/v1/reviews/1"),
        ("GET", "/api/threads/1/reviews"),
    ],
)
async def test_former_review_routes_return_standard_json_404(
    auth_client: AsyncClient,
    method: str,
    path: str,
) -> None:
    """Former review methods are no longer registered or executable."""
    response = await auth_client.request(method, path, json={})

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.asyncio
async def test_reviews_are_absent_from_openapi(auth_client: AsyncClient) -> None:
    """The retired Reviews surface is not advertised in the API contract."""
    response = await auth_client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    # Check for actual Reviews API paths (e.g., /api/v1/reviews/... and
    # /api/threads/{id}/reviews), not incidental substrings like "preview"
    # in other endpoints. The retired surface must stay unregistered.
    assert not any(re.search(r"/reviews?(?=/|$)", path) for path in paths)
