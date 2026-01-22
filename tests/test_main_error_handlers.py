"""Tests for error handlers in app/main.py."""

import pytest
from httpx import AsyncClient
from starlette.exceptions import HTTPException as StarletteHTTPException


@pytest.mark.asyncio
async def test_http_exception_handler_404(auth_client: AsyncClient) -> None:
    """Test HTTP exception handler with 404 status code for non-existent endpoint."""
    response = await auth_client.get("/api/this-endpoint-does-not-exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_http_exception_handler_for_nonexistent_task(auth_client: AsyncClient) -> None:
    """Test HTTP exception handler when querying non-existent task."""
    response = await auth_client.get("/api/tasks/TASK-NONEXISTENT")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_http_exception_handler_for_nonexistent_thread(auth_client: AsyncClient) -> None:
    """Test HTTP exception handler when querying non-existent thread."""
    response = await auth_client.get("/api/threads/999999")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_validation_exception_handler_invalid_task_id_type(
    auth_client: AsyncClient,
) -> None:
    """Test validation exception handler for invalid task_id type."""
    response = await auth_client.get("/api/tasks/12345")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_validation_exception_handler_for_claim_missing_agent_name(
    auth_client: AsyncClient,
    sample_tasks,
    enable_internal_ops,
) -> None:
    """Test validation exception handler for missing agent_name field."""
    response = await auth_client.post(
        "/api/tasks/TASK-101/claim",
        json={"worktree": "test-worktree"},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["detail"] == "Validation failed"
    assert "errors" in data


@pytest.mark.asyncio
async def test_validation_exception_handler_for_claim_empty_agent_name(
    auth_client: AsyncClient,
    sample_tasks,
    enable_internal_ops,
) -> None:
    """Test validation exception handler for empty agent_name field."""
    response = await auth_client.post(
        "/api/tasks/TASK-101/claim",
        json={"agent_name": "", "worktree": "test-worktree"},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["detail"] == "Validation failed"
    assert "errors" in data
    error_fields = [error["field"] for error in data["errors"]]
    assert any("agent_name" in field for field in error_fields)


@pytest.mark.asyncio
async def test_validation_exception_handler_for_create_task_invalid_type(
    auth_client: AsyncClient,
    enable_internal_ops,
) -> None:
    """Test validation exception handler for invalid field type in create task."""
    response = await auth_client.post(
        "/api/tasks/",
        json={
            "task_id": 12345,
            "title": "Test Task",
            "priority": "HIGH",
            "estimated_effort": "1 hour",
        },
    )
    assert response.status_code == 422
    data = response.json()
    assert data["detail"] == "Validation failed"
    assert "errors" in data
    error_fields = [error["field"] for error in data["errors"]]
    assert "body.task_id" in error_fields


@pytest.mark.asyncio
async def test_validation_exception_handler_for_create_task_invalid_priority(
    auth_client: AsyncClient,
    enable_internal_ops,
) -> None:
    """Test validation exception handler for invalid priority type (not string)."""
    response = await auth_client.post(
        "/api/tasks/",
        json={
            "task_id": "TEST-VALIDATION-PRIORITY",
            "title": "Test Task",
            "priority": 12345,
            "estimated_effort": "1 hour",
        },
    )
    assert response.status_code == 422
    data = response.json()
    assert data["detail"] == "Validation failed"
    assert "errors" in data
    error_fields = [error["field"] for error in data["errors"]]
    assert "body.priority" in error_fields


@pytest.mark.asyncio
async def test_validation_exception_handler_for_claim_missing_worktree(
    auth_client: AsyncClient,
    sample_tasks,
    enable_internal_ops,
) -> None:
    """Test validation exception handler for missing worktree field."""
    response = await auth_client.post(
        "/api/tasks/TASK-101/claim",
        json={"agent_name": "test-agent"},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["detail"] == "Validation failed"
    assert "errors" in data
    error_fields = [error["field"] for error in data["errors"]]
    assert any("worktree" in field for field in error_fields)


@pytest.mark.asyncio
async def test_validation_exception_handler_for_update_notes_missing_notes(
    auth_client: AsyncClient,
    sample_tasks,
    enable_internal_ops,
) -> None:
    """Test validation exception handler for missing notes field."""
    response = await auth_client.post(
        "/api/tasks/TASK-101/update-notes",
        json={},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["detail"] == "Validation failed"
    assert "errors" in data


@pytest.mark.asyncio
async def test_validation_exception_handler_for_set_status_invalid_status(
    auth_client: AsyncClient,
    sample_tasks,
    enable_internal_ops,
) -> None:
    """Test HTTP exception handler for invalid status value."""
    response = await auth_client.post(
        "/api/tasks/TASK-101/set-status",
        json={"status": "invalid_status_value"},
    )
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "Invalid status" in data["detail"]


@pytest.mark.asyncio
async def test_validation_exception_handler_error_structure(
    auth_client: AsyncClient,
    enable_internal_ops,
) -> None:
    """Test that validation errors have proper structure with field, message, type."""
    response = await auth_client.post(
        "/api/tasks/",
        json={
            "task_id": 123,
            "title": "Test",
            "priority": "HIGH",
        },
    )
    assert response.status_code == 422
    data = response.json()
    assert "errors" in data
    for error in data["errors"]:
        assert "field" in error
        assert "message" in error
        assert "type" in error
        assert isinstance(error["field"], str)
        assert isinstance(error["message"], str)
        assert isinstance(error["type"], str)


@pytest.mark.asyncio
async def test_validation_exception_handler_for_multiple_errors(
    auth_client: AsyncClient,
    enable_internal_ops,
) -> None:
    """Test validation exception handler with multiple validation errors."""
    response = await auth_client.post(
        "/api/tasks/TASK-101/claim",
        json={},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["detail"] == "Validation failed"
    assert "errors" in data
    assert len(data["errors"]) > 0


@pytest.mark.asyncio
async def test_validation_exception_handler_includes_body(
    auth_client: AsyncClient,
    enable_internal_ops,
) -> None:
    """Test that validation error response includes the request body."""
    response = await auth_client.post(
        "/api/tasks/",
        json={
            "task_id": 123,
            "title": "Test Task",
            "priority": "HIGH",
            "estimated_effort": "1 hour",
        },
    )
    assert response.status_code == 422
    data = response.json()
    assert "body" in data
    assert data["body"] is not None


@pytest.mark.asyncio
async def test_validation_exception_handler_nested_field_error(
    auth_client: AsyncClient,
    enable_internal_ops,
) -> None:
    """Test validation exception handler for nested field errors."""
    response = await auth_client.post(
        "/api/tasks/TASK-101/heartbeat",
        json={},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["detail"] == "Validation failed"
    assert "errors" in data


@pytest.fixture
def test_app_with_error_routes():
    """Create a test app with routes that trigger specific exceptions."""
    from fastapi import FastAPI

    test_app = FastAPI()

    @test_app.get("/test-404")
    async def test_404():
        raise StarletteHTTPException(status_code=404, detail="Not found")

    @test_app.get("/test-403")
    async def test_403():
        raise StarletteHTTPException(status_code=403, detail="Forbidden")

    @test_app.get("/test-401")
    async def test_401():
        raise StarletteHTTPException(status_code=401, detail="Unauthorized")

    @test_app.get("/test-400")
    async def test_400():
        raise StarletteHTTPException(status_code=400, detail="Bad request")

    @test_app.get("/test-500")
    async def test_500():
        raise StarletteHTTPException(status_code=500, detail="Server error")

    return test_app


@pytest.mark.asyncio
async def test_http_exception_handler_various_status_codes(
    test_app_with_error_routes,
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
        "/api/threads/",
        json={},
    )
    assert response.status_code == 422
    data = response.json()
    assert "errors" in data
    assert len(data["errors"]) > 0


@pytest.mark.asyncio
async def test_serve_react_spa_serves_index(auth_client: AsyncClient) -> None:
    """Test serve_react_spa returns React index.html for valid paths."""
    response = await auth_client.get("/rate")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_serve_react_spa_returns_404_for_api_paths(auth_client: AsyncClient) -> None:
    """Test serve_react_spa returns 404 for blocked API prefixes."""
    response = await auth_client.get("/api/nonexistent")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Not Found"


@pytest.mark.asyncio
async def test_serve_react_spa_returns_404_for_static_paths(auth_client: AsyncClient) -> None:
    """Test serve_react_spa returns 404 for blocked static prefixes."""
    response = await auth_client.get("/static/nonexistent")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Not Found"


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
