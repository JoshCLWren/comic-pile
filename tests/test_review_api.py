"""Removal-contract tests for the retired Reviews API."""

import re

import pytest
from httpx import AsyncClient


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


