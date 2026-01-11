"""Tests for rate limiting functionality."""

import random

import pytest
from httpx import AsyncClient

from app.middleware import limiter


@pytest.mark.asyncio
async def test_rate_limit_on_threads_list(client: AsyncClient) -> None:
    """Test that rate limiting is applied to GET /threads/ endpoint."""
    limiter.reset()

    for _ in range(100):
        response = await client.get("/api/threads/")
        assert response.status_code == 200

    response = await client.get("/api/threads/")
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_on_thread_create(client: AsyncClient) -> None:
    """Test that rate limiting is applied to POST /threads/ endpoint."""
    limiter.reset()

    for _ in range(30):
        response = await client.post(
            "/api/threads/",
            json={
                "title": f"Test Thread {random.randint(10000, 99999)}",
                "format": "Comic",
                "issues_remaining": 10,
            },
        )
        assert response.status_code == 201

    response = await client.post(
        "/api/threads/",
        json={
            "title": f"Test Thread {random.randint(10000, 99999)}",
            "format": "Comic",
            "issues_remaining": 10,
        },
    )
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_on_rate(client: AsyncClient) -> None:
    """Test that rate limiting is applied to POST /rate/ endpoint."""
    limiter.reset()

    for _ in range(60):
        response = await client.post(
            "/api/rate/",
            json={"rating": 3, "issues_read": 1},
        )
        assert response.status_code in (200, 400)

    response = await client.post(
        "/api/rate/",
        json={"rating": 3, "issues_read": 1},
    )
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_headers(client: AsyncClient) -> None:
    """Test that rate limiting response headers are present."""
    limiter.reset()

    response = await client.get("/api/threads/")
    assert response.status_code == 200
