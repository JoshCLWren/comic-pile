"""Tests for error handlers in app/main.py."""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from starlette.exceptions import HTTPException as StarletteHTTPException


@pytest.mark.asyncio
async def test_http_exception_handler_404(auth_client: AsyncClient) -> None:
    """Test HTTP exception handler with 404 status code for non-existent endpoint."""
    response = await auth_client.get("/api/v1/this-endpoint-does-not-exist")
    assert response.status_code == 404
    data = response.json()
    # New Google-style error format
    assert "error" in data
    assert data["error"]["code"] == 404
    assert data["error"]["status"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_http_exception_handler_for_nonexistent_thread(auth_client: AsyncClient) -> None:
    """Test HTTP exception handler when querying non-existent thread."""
    response = await auth_client.get("/api/v1/threads/999999")
    assert response.status_code == 404
    data = response.json()
    # New Google-style error format
    assert "error" in data
    assert data["error"]["code"] == 404
    assert data["error"]["status"] == "NOT_FOUND"


@pytest.fixture
def test_app_with_error_routes() -> FastAPI:
    """Create a test app with routes that trigger specific exceptions."""
    test_app = FastAPI()

    @test_app.get("/test-404")
    async def test_404() -> None:
        raise StarletteHTTPException(status_code=404, detail="Not found")

    @test_app.get("/test-403")
    async def test_403() -> None:
        raise StarletteHTTPException(status_code=403, detail="Forbidden")

    @test_app.get("/test-401")
    async def test_401() -> None:
        raise StarletteHTTPException(status_code=401, detail="Unauthorized")

    @test_app.get("/test-400")
    async def test_400() -> None:
        raise StarletteHTTPException(status_code=400, detail="Bad request")

    @test_app.get("/test-500")
    async def test_500() -> None:
        raise StarletteHTTPException(status_code=500, detail="Server error")

    return test_app


@pytest.mark.asyncio
async def test_http_exception_handler_various_status_codes(
    test_app_with_error_routes: FastAPI,
) -> None:
    """Test HTTP exception handler with various status codes."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=test_app_with_error_routes)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response_404 = await ac.get("/test-404")
        assert response_404.status_code == 404
        data_404 = response_404.json()
        assert data_404["detail"] == "Not found"

        response_403 = await ac.get("/test-403")
        assert response_403.status_code == 403
        data_403 = response_403.json()
        assert data_403["detail"] == "Forbidden"

        response_401 = await ac.get("/test-401")
        assert response_401.status_code == 401
        data_401 = response_401.json()
        assert data_401["detail"] == "Unauthorized"

        response_400 = await ac.get("/test-400")
        assert response_400.status_code == 400
        data_400 = response_400.json()
        assert data_400["detail"] == "Bad request"

        response_500 = await ac.get("/test-500")
        assert response_500.status_code == 500
        data_500 = response_500.json()
        assert data_500["detail"] == "Server error"


@pytest.mark.asyncio
async def test_validation_exception_handler_for_thread_create_missing_fields(
    auth_client: AsyncClient,
) -> None:
    """Test validation exception handler for thread creation with missing required fields."""
    response = await auth_client.post(
        "/api/v1/threads/",
        json={},
    )
    assert response.status_code == 422
    data = response.json()
    # New Google-style error format
    assert "error" in data
    assert data["error"]["code"] == 422
    assert data["error"]["status"] == "INVALID_ARGUMENT"
    assert "details" in data["error"]
    assert len(data["error"]["details"]) > 0


@pytest.mark.asyncio
async def test_serve_react_spa_serves_index(auth_client: AsyncClient) -> None:
    """Test serve_react_spa returns React index.html for valid paths."""
    response = await auth_client.get("/rate")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_serve_react_spa_returns_404_for_api_paths(auth_client: AsyncClient) -> None:
    """Test serve_react_spa returns 404 for blocked API prefixes."""
    response = await auth_client.get("/api/v1/nonexistent")
    assert response.status_code == 404
    data = response.json()
    # New Google-style error format
    assert "error" in data
    assert data["error"]["code"] == 404
    assert data["error"]["message"] == "Not Found"


@pytest.mark.asyncio
async def test_serve_react_spa_returns_404_for_static_paths(auth_client: AsyncClient) -> None:
    """Test serve_react_spa returns 404 for blocked static prefixes."""
    response = await auth_client.get("/static/nonexistent")
    assert response.status_code == 404
    data = response.json()
    # New Google-style error format
    assert "error" in data
    assert data["error"]["code"] == 404
    assert data["error"]["message"] == "Not Found"


@pytest.mark.asyncio
async def test_serve_react_spa_serves_queue_page(auth_client: AsyncClient) -> None:
    """Test serve_react_spa serves React app for /queue."""
    response = await auth_client.get("/queue")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_serve_react_spa_serves_history_page(auth_client: AsyncClient) -> None:
    """Test serve_react_spa serves React app for /history."""
    response = await auth_client.get("/history")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
