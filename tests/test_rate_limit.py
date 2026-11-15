"""Tests for rate limiting functionality."""

import random

import pytest
from httpx import AsyncClient

from app.middleware import limiter


@pytest.mark.asyncio
async def test_rate_limit_on_thread_create(auth_client: AsyncClient) -> None:
    """Test that rate limiting is applied to POST /threads/ endpoint."""
    limiter.reset()

    for _ in range(30):
        response = await auth_client.post(
            "/api/v1/threads/",
            json={
                "title": f"Test Thread {random.randint(10000, 99999)}",
                "format": "Comic",
                "issues_remaining": 10,
            },
        )
        assert response.status_code == 201

    response = await auth_client.post(
        "/api/v1/threads/",
        json={
            "title": f"Test Thread {random.randint(10000, 99999)}",
            "format": "Comic",
            "issues_remaining": 10,
        },
    )
    assert response.status_code == 429
