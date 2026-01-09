"""Tests for rate limiting functionality."""

import random

from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from app.main import app


async def test_rate_limit_on_tasks_list(client: AsyncClient) -> None:
    """Test that rate limiting is applied to GET /api/tasks/ endpoint."""
    for _ in range(200):
        response = await client.get("/api/api/tasks/")
        assert response.status_code == 200

    response = await client.get("/api/api/tasks/")
    assert response.status_code == 429
    assert "rate limit" in response.json()["error"].lower()


async def test_rate_limit_on_tasks_create(client: AsyncClient) -> None:
    """Test that rate limiting is applied to POST /api/tasks/ endpoint."""
    for _ in range(60):
        response = await client.post(
            "/api/tasks/",
            json={
                "task_id": f"test-task-{random.randint(10000, 99999)}",
                "title": "Test Task",
                "description": "Test Description",
                "instructions": "Test Instructions",
                "priority": "MEDIUM",
                "task_type": "feature",
                "estimated_effort": "2 hours",
            },
        )
        assert response.status_code == 201

    response = await client.post(
        "/api/tasks/",
        json={
            "task_id": f"test-task-{random.randint(10000, 99999)}",
            "title": "Test Task",
            "description": "Test Description",
            "instructions": "Test Instructions",
            "priority": "MEDIUM",
            "task_type": "feature",
            "estimated_effort": "2 hours",
        },
    )
    assert response.status_code == 429


async def test_rate_limit_on_threads_list(client: AsyncClient) -> None:
    """Test that rate limiting is applied to GET /threads/ endpoint."""
    for _ in range(100):
        response = await client.get("/api/threads/")
        assert response.status_code == 200

    response = await client.get("/api/threads/")
    assert response.status_code == 429


async def test_rate_limit_on_thread_create(client: AsyncClient) -> None:
    """Test that rate limiting is applied to POST /threads/ endpoint."""
    for _ in range(30):
        response = await client.post(
            "/threads/",
            json={
                "title": f"Test Thread {random.randint(10000, 99999)}",
                "format": "Comic",
                "issues_remaining": 10,
            },
        )
        assert response.status_code == 201

    response = await client.post(
        "/threads/",
        json={
            "title": f"Test Thread {random.randint(10000, 99999)}",
            "format": "Comic",
            "issues_remaining": 10,
        },
    )
    assert response.status_code == 429


async def test_rate_limit_on_roll(client: AsyncClient) -> None:
    """Test that rate limiting is applied to POST /roll/ endpoint."""
    for _ in range(30):
        response = await client.post("/api/roll/")
        assert response.status_code in (200, 400)

    response = await client.post("/api/roll/")
    assert response.status_code == 429


async def test_rate_limit_on_roll_html(client: AsyncClient) -> None:
    """Test that rate limiting is applied to POST /roll/html endpoint."""
    for _ in range(30):
        response = await client.post("/api/roll/html")
        assert response.status_code in (200, 400)

    response = await client.post("/api/roll/html")
    assert response.status_code == 429


async def test_rate_limit_on_rate(client: AsyncClient) -> None:
    """Test that rate limiting is applied to POST /rate/ endpoint."""
    for _ in range(60):
        response = await client.post(
            "/rate/",
            json={"rating": 3, "issues_read": 1},
        )
        assert response.status_code in (200, 400)

    response = await client.post(
        "/rate/",
        json={"rating": 3, "issues_read": 1},
    )
    assert response.status_code == 429


async def test_rate_limit_on_queue_move(client: AsyncClient) -> None:
    """Test that rate limiting is applied to queue movement endpoints."""
    response = await client.post(
        "/threads/",
        json={
            "title": "Test Thread for Queue",
            "format": "Comic",
            "issues_remaining": 10,
        },
    )
    assert response.status_code == 201
    thread_id = response.json()["id"]

    for _ in range(30):
        response = await client.put(f"/queue/threads/{thread_id}/front/")
        assert response.status_code == 200

    response = await client.put(f"/queue/threads/{thread_id}/front/")
    assert response.status_code == 429


async def test_rate_limit_on_session_current(client: AsyncClient) -> None:
    """Test that rate limiting is applied to GET /sessions/current/ endpoint."""
    response = await client.post("/api/sessions/")
    assert response.status_code == 201

    for _ in range(200):
        response = await client.get("/api/sessions/current/")
        assert response.status_code == 200

    response = await client.get("/api/sessions/current/")
    assert response.status_code == 429


async def test_rate_limit_headers(client: AsyncClient) -> None:
    """Test that rate limiting is applied to endpoints."""
    response = await client.get("/api/threads/")
    assert response.status_code == 200


async def test_rate_limit_reset_after_time_window(client: AsyncClient, db: Session) -> None:
    """Test that rate limit resets after the time window expires."""
    import time

    for _ in range(100):
        response = await client.get("/api/threads/")
        assert response.status_code == 200

    response = await client.get("/api/threads/")
    assert response.status_code == 429

    time.sleep(60)

    response = await client.get("/api/threads/")
    assert response.status_code == 200


async def test_rate_limit_by_ip(client: AsyncClient) -> None:
    """Test that rate limiting is applied per IP address."""
    import asyncio

    async def make_requests_from_ip(ip: str) -> int:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Forwarded-For": ip},
        ) as ip_client:
            success_count = 0
            for _ in range(150):
                response = await ip_client.get("/api/threads/")
                if response.status_code == 200:
                    success_count += 1
            return success_count

    results = await asyncio.gather(
        make_requests_from_ip("192.168.1.1"),
        make_requests_from_ip("192.168.1.2"),
    )

    assert all(count == 100 for count in results)


async def test_no_rate_limit_on_health_check(client: AsyncClient) -> None:
    """Test that health check endpoint has no rate limit."""
    for _ in range(500):
        response = await client.get("/api/health")
        assert response.status_code == 200


async def test_rate_limit_exceeded_message(client: AsyncClient) -> None:
    """Test that rate limit exceeded returns helpful error message."""
    for _ in range(101):
        await client.get("/api/threads/")

    response = await client.get("/api/threads/")
    assert response.status_code == 429
    data = response.json()
    assert "error" in data
    assert "rate limit" in data["error"].lower()
