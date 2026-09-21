"""Application-specific exception classes."""

from __future__ import annotations

from typing import Any


class DatabaseUnavailableError(Exception):
    """Raised when the database is temporarily unavailable due to resource exhaustion or connection failure.

    This exception represents a retryable infrastructure dependency failure, not an application bug.
    It should be caught at the application boundary and converted to a 503 Service Unavailable response.

    Attributes:
        original_error: The underlying exception that caused this error.
        error_class: The class name of the original exception for structured logging.
        sqlstate: The PostgreSQL SQLSTATE code if available.
    """

    def __init__(
        self,
        message: str,
        *,
        original_error: BaseException | None = None,
        error_class: str | None = None,
        sqlstate: str | None = None,
    ) -> None:
        super().__init__(message)
        self.original_error = original_error
        self.error_class = error_class or (type(original_error).__name__ if original_error else None)
        self.sqlstate = sqlstate

    def to_log_context(self) -> dict[str, Any]:
        """Return structured context for server-side logging without sensitive data."""
        return {
            "error_class": self.error_class,
            "sqlstate": self.sqlstate,
            "message": str(self),
        }