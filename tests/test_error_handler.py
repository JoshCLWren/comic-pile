"""Test error handler functionality."""

from unittest.mock import Mock, patch

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


def test_is_known_5xx_error_database_connection():
    """Test detection of database connection errors."""
    exc = OperationalError("database connection failed")
    is_known, error_info = error_handler.is_known_5xx_error(
        exc, "OperationalError", "database connection failed"
    )
    assert is_known is True
    assert error_info is not None
    assert error_info["create_issue"] is True
    assert error_info["priority"] == "high"


def test_is_known_5xx_error_query_timeout():
    """Test detection of query timeout errors."""
    exc = QueryTimeoutError("statement timeout")
    is_known, error_info = error_handler.is_known_5xx_error(
        exc, "QueryTimeoutError", "statement timeout"
    )
    assert is_known is True
    assert error_info is not None
    assert error_info["create_issue"] is True
    assert error_info["priority"] == "high"


def test_is_known_5xx_error_constraint_violation():
    """Test detection of constraint violation errors."""
    exc = IntegrityError("foreign key constraint")
    is_known, error_info = error_handler.is_known_5xx_error(
        exc, "IntegrityError", "foreign key constraint"
    )
    assert is_known is True
    assert error_info is not None
    assert error_info["create_issue"] is True
    assert error_info["priority"] == "high"


def test_is_known_5xx_error_temporary():
    """Test detection of temporary server errors."""
    exc = TransientError("temporary failure")
    is_known, error_info = error_handler.is_known_5xx_error(
        exc, "TransientError", "temporary failure"
    )
    assert is_known is True
    assert error_info is not None
    assert error_info["create_issue"] is False


def test_is_known_5xx_error_unknown():
    """Test handling of unknown errors."""
    exc = SomeRandomError("unknown issue")
    is_known, error_info = error_handler.is_known_5xx_error(exc, "SomeRandomError", "unknown issue")
    assert is_known is False
    assert error_info is None


@patch("app.api.error_handler.GitHubTaskClient")
def test_handle_5xx_error_known_with_issue(mock_github_client_class, mock_request):
    """Test handling known 5xx errors that create GitHub issues."""
    mock_client = Mock()
    mock_github_client_class.return_value = mock_client
    mock_client.create_task.return_value = {"id": 123, "title": "Test Issue"}

    exc = OperationalError("database connection failed")
    result = error_handler.handle_5xx_error(exc, mock_request)

    assert result["action"] == "issue_created"
    assert result["error_type"] == "OperationalError"
    assert error_handler.ERROR_COUNTER["total_5xx"] == 1

    mock_client.create_task.assert_called_once()
    call_args = mock_client.create_task.call_args
    assert "5xx Error: OperationalError" in call_args[1]["title"]
    assert call_args[1]["priority"] == "high"
    assert call_args[1]["task_type"] == "bug"


@patch("app.api.error_handler.GitHubTaskClient")
def test_handle_5xx_error_known_no_issue(mock_github_client_class, mock_request):
    """Test handling known temporary errors (no issue created)."""
    mock_client = Mock()
    mock_github_client_class.return_value = mock_client

    exc = TransientError("temporary failure")
    result = error_handler.handle_5xx_error(exc, mock_request)

    assert result["action"] == "logged"
    assert result["error_type"] == "TransientError"
    assert error_handler.ERROR_COUNTER["total_5xx"] == 1

    mock_client.create_task.assert_not_called()


def test_handle_5xx_error_unknown(mock_request):
    """Test handling unknown errors (no issue created)."""
    exc = SomeRandomError("unknown issue")
    result = error_handler.handle_5xx_error(exc, mock_request)

    assert result["action"] == "logged"
    assert result["error_type"] == "SomeRandomError"
    assert error_handler.ERROR_COUNTER["total_5xx"] == 1


@patch("app.api.error_handler.GitHubTaskClient")
def test_create_github_issue_with_full_debug_info(mock_github_client_class, mock_request):
    """Test that error issues capture full debugging information."""
    mock_client = Mock()
    mock_github_client_class.return_value = mock_client
    mock_client.create_task.return_value = {"id": 123, "title": "Test Issue"}

    exc = IntegrityError("unique constraint violation")
    error_info = {
        "create_issue": True,
        "priority": "high",
        "estimated_effort": "1 hour",
        "keywords": ["IntegrityError"],
    }

    error_handler.create_github_issue(
        request_body=mock_request.state.request_body,
        path=mock_request.url.path,
        http_method=mock_request.method,
        path_params=mock_request.path_params,
        headers=dict(mock_request.headers),
        error=exc,
        error_info=error_info,
    )

    mock_client.create_task.assert_called_once()
    call_args = mock_client.create_task.call_args

    assert "5xx Error: IntegrityError" in call_args[1]["title"]
    assert "Error Details" in call_args[1]["description"]
    assert "Error Type: IntegrityError" in call_args[1]["description"]
    assert "Path: POST /test/path" in call_args[1]["description"]
    assert "Path Parameters:" in call_args[1]["description"]
    assert "Headers:" in call_args[1]["description"]
    assert "Request Body:" in call_args[1]["description"]
    assert "unique constraint violation" in call_args[1]["description"]
    assert "Instructions" in call_args[1]["description"]
    assert call_args[1]["priority"] == "high"
    assert call_args[1]["task_type"] == "bug"


def test_get_error_stats():
    """Test getting error statistics."""
    error_handler.ERROR_COUNTER = {"total_5xx": 5}
    stats = error_handler.get_error_stats()
    assert stats == {"total_5xx": 5}
    assert stats is not error_handler.ERROR_COUNTER


def test_multiple_errors_increment_counter(mock_request):
    """Test that multiple errors increment the counter."""
    for i in range(3):
        exc = Exception(f"Error {i}")
        error_handler.handle_5xx_error(exc, mock_request)

    assert error_handler.ERROR_COUNTER["total_5xx"] == 3
