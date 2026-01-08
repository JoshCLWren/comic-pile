"""Test error handler functionality."""

import json
from unittest.mock import Mock

import pytest
from fastapi import Request
from starlette.datastructures import Headers

from app.api import error_handler


class OperationalError(Exception):
    """Mock database connection error."""
    pass


class QueryTimeoutError(Exception):
    """Mock query timeout error."""
    pass


class IntegrityError(Exception):
    """Mock constraint violation error."""
    pass


class TransientError(Exception):
    """Mock temporary server error."""
    pass


class SomeRandomError(Exception):
    """Mock unknown error."""
    pass


@pytest.fixture(autouse=True)
def reset_error_counter():
    """Reset error counter before each test."""
    error_handler.ERROR_COUNTER = {"total_5xx": 0}
    yield
    error_handler.ERROR_COUNTER = {"total_5xx": 0}


@pytest.fixture
def mock_request():
    """Create a mock request object."""
    request = Mock(spec=Request)
    request.url.path = "/test/path"
    request.method = "POST"
    request.path_params = {"thread_id": "123"}
    request.headers = Headers({"content-type": "application/json", "authorization": "Bearer test"})
    request.state = Mock()
    request.state.request_body = {"test": "data"}
    return request


@pytest.fixture
def temp_tasks_file(tmp_path):
    """Create a temporary tasks.json file for testing."""
    tasks_file = tmp_path / "tasks.json"
    original_tasks_file = error_handler.TASKS_FILE
    error_handler.TASKS_FILE = tasks_file
    yield tasks_file
    error_handler.TASKS_FILE = original_tasks_file


def test_is_known_5xx_error_database_connection():
    """Test detection of database connection errors."""
    exc = OperationalError("database connection failed")
    is_known, error_info = error_handler.is_known_5xx_error(exc, "OperationalError", "database connection failed")
    assert is_known is True
    assert error_info is not None
    assert error_info["create_task"] is True
    assert error_info["priority"] == "HIGH"


def test_is_known_5xx_error_query_timeout():
    """Test detection of query timeout errors."""
    exc = QueryTimeoutError("statement timeout")
    is_known, error_info = error_handler.is_known_5xx_error(exc, "QueryTimeoutError", "statement timeout")
    assert is_known is True
    assert error_info is not None
    assert error_info["create_task"] is True
    assert error_info["priority"] == "HIGH"


def test_is_known_5xx_error_constraint_violation():
    """Test detection of constraint violation errors."""
    exc = IntegrityError("foreign key constraint")
    is_known, error_info = error_handler.is_known_5xx_error(exc, "IntegrityError", "foreign key constraint")
    assert is_known is True
    assert error_info is not None
    assert error_info["create_task"] is True
    assert error_info["priority"] == "HIGH"


def test_is_known_5xx_error_temporary():
    """Test detection of temporary server errors."""
    exc = TransientError("temporary failure")
    is_known, error_info = error_handler.is_known_5xx_error(exc, "TransientError", "temporary failure")
    assert is_known is True
    assert error_info is not None
    assert error_info["create_task"] is False


def test_is_known_5xx_error_unknown():
    """Test handling of unknown errors."""
    exc = SomeRandomError("unknown issue")
    is_known, error_info = error_handler.is_known_5xx_error(exc, "SomeRandomError", "unknown issue")
    assert is_known is False
    assert error_info is None


def test_handle_5xx_error_known_with_task(mock_request, temp_tasks_file):
    """Test handling known 5xx errors that create tasks."""
    exc = OperationalError("database connection failed")
    result = error_handler.handle_5xx_error(exc, mock_request)

    assert result["action"] == "task_created"
    assert result["error_type"] == "OperationalError"
    assert error_handler.ERROR_COUNTER["total_5xx"] == 1

    # Verify task was created in tasks.json
    with open(temp_tasks_file) as f:
        tasks = json.load(f)
    assert len(tasks["tasks"]) == 1
    assert tasks["tasks"][0]["task_id"].startswith("API-ERROR-")
    assert tasks["tasks"][0]["status"] == "pending"
    assert tasks["tasks"][0]["priority"] == "HIGH"
    assert tasks["tasks"][0]["task_type"] == "bug"


def test_handle_5xx_error_known_no_task(mock_request):
    """Test handling known temporary errors (no task created)."""
    exc = TransientError("temporary failure")
    result = error_handler.handle_5xx_error(exc, mock_request)

    assert result["action"] == "logged"
    assert result["error_type"] == "TransientError"
    assert error_handler.ERROR_COUNTER["total_5xx"] == 1


def test_handle_5xx_error_unknown(mock_request):
    """Test handling unknown errors (no task created)."""
    exc = SomeRandomError("unknown issue")
    result = error_handler.handle_5xx_error(exc, mock_request)

    assert result["action"] == "logged"
    assert result["error_type"] == "SomeRandomError"
    assert error_handler.ERROR_COUNTER["total_5xx"] == 1


def test_create_error_task_with_full_debug_info(mock_request, temp_tasks_file):
    """Test that error tasks capture full debugging information."""
    exc = IntegrityError("unique constraint violation")
    error_info = {
        "create_task": True,
        "priority": "HIGH",
        "estimated_effort": "1 hour",
        "keywords": ["IntegrityError"],
    }

    error_handler.create_error_task(
        request_body=mock_request.state.request_body,
        path=mock_request.url.path,
        http_method=mock_request.method,
        path_params=mock_request.path_params,
        headers=dict(mock_request.headers),
        error=exc,
        error_info=error_info,
        request=mock_request,
    )

    # Verify task contains all required debugging info
    with open(temp_tasks_file) as f:
        tasks = json.load(f)
    assert len(tasks["tasks"]) == 1

    task = tasks["tasks"][0]
    assert task["title"] == "5xx Error: IntegrityError"
    assert task["description"]["request_body"] == {"test": "data"}
    assert task["description"]["path"] == "/test/path"
    assert task["description"]["http_method"] == "POST"
    assert task["description"]["path_params"] == {"thread_id": "123"}
    assert "content-type" in task["description"]["headers"]
    assert "authorization" in task["description"]["headers"]
    assert "unique constraint violation" in task["description"]["error"]
    assert "traceback" in task["description"]
    assert task["priority"] == "HIGH"
    assert task["status"] == "pending"
    assert task["task_type"] == "bug"
    assert task["estimated_effort"] == "1 hour"


def test_get_error_stats():
    """Test getting error statistics."""
    error_handler.ERROR_COUNTER = {"total_5xx": 5}
    stats = error_handler.get_error_stats()
    assert stats == {"total_5xx": 5}
    assert stats is not error_handler.ERROR_COUNTER  # Should return a copy


def test_multiple_errors_increment_counter(mock_request):
    """Test that multiple errors increment the counter."""
    for i in range(3):
        exc = Exception(f"Error {i}")
        error_handler.handle_5xx_error(exc, mock_request)

    assert error_handler.ERROR_COUNTER["total_5xx"] == 3
