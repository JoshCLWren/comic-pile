"""Google-style error response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Individual error detail following Google API Design Guide.

    Used for field-level validation errors or multiple error conditions.
    """

    field: str | None = Field(None, description="Field that caused the error")
    reason: str = Field(..., description="Machine-readable error reason")
    message: str = Field(..., description="Human-readable error message")
    location: str | None = Field(None, description="Location of the error (e.g., 'body', 'query')")


class ErrorResponse(BaseModel):
    """Standard error response following Google API Design Guide.

    Example:
        {
            "error": {
                "code": 404,
                "message": "Thread 123 not found",
                "status": "NOT_FOUND",
                "details": []
            }
        }
    """

    code: int = Field(..., description="HTTP status code")
    message: str = Field(..., description="Human-readable error message")
    status: str = Field(..., description="HTTP status name (e.g., NOT_FOUND, INTERNAL)")
    details: list[ErrorDetail] = Field(default_factory=list, description="Additional error details")


class ErrorResponseWrapper(BaseModel):
    """Top-level wrapper for error responses."""

    error: ErrorResponse


def http_status_to_name(status_code: int) -> str:
    """Convert HTTP status code to Google-style status name.

    Args:
        status_code: HTTP status code (e.g., 404)

    Returns:
        Status name (e.g., "NOT_FOUND")
    """
    status_map = {
        400: "INVALID_ARGUMENT",
        401: "UNAUTHENTICATED",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        409: "ALREADY_EXISTS",
        422: "INVALID_ARGUMENT",
        429: "RESOURCE_EXHAUSTED",
        500: "INTERNAL",
        501: "NOT_IMPLEMENTED",
        503: "UNAVAILABLE",
        504: "DEADLINE_EXCEEDED",
    }
    return status_map.get(status_code, "UNKNOWN")


def create_error_response(
    status_code: int,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> dict[str, Any]:
    """Create a standardized error response.

    Args:
        status_code: HTTP status code
        message: Human-readable error message
        details: Optional list of ErrorDetail objects

    Returns:
        Dictionary with error response structure
    """
    # Convert ErrorDetail objects to dicts for JSON serialization
    details_list = [d.model_dump(exclude_none=True) for d in (details or [])]

    return {
        "error": {
            "code": status_code,
            "message": message,
            "status": http_status_to_name(status_code),
            "details": details_list,
        }
    }
