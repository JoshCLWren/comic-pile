"""Performance budget enforcement and bounded await primitives."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

logger = logging.getLogger(__name__)

# Performance budget constants (in milliseconds)
STARTUP_WARNING_MS = 2000
STARTUP_TIMEOUT_MS = 2500
REQUEST_WARNING_MS = 500
REQUEST_TIMEOUT_MS = 1000

T = TypeVar("T")


class PerformanceBudgetError(Exception):
    """Base class for performance budget violations."""


class StartupBudgetError(PerformanceBudgetError):
    """Raised when startup performance budget is exceeded."""

    def __init__(self, operation: str, elapsed_ms: float, timeout_ms: float) -> None:
        """Initialize the startup budget error.

        Args:
            operation: Name of the operation that exceeded the budget.
            elapsed_ms: Elapsed time in milliseconds.
            timeout_ms: Configured hard timeout in milliseconds.
        """
        self.operation = operation
        self.elapsed_ms = elapsed_ms
        self.timeout_ms = timeout_ms
        super().__init__(
            f"Startup budget exceeded for operation '{operation}': "
            f"{elapsed_ms:.2f}ms (limit: {timeout_ms}ms)"
        )


class RequestBudgetError(PerformanceBudgetError):
    """Raised when request performance budget is exceeded."""

    def __init__(self, operation: str, elapsed_ms: float, timeout_ms: float) -> None:
        """Initialize the request budget error.

        Args:
            operation: Name of the operation that exceeded the budget.
            elapsed_ms: Elapsed time in milliseconds.
            timeout_ms: Configured hard timeout in milliseconds.
        """
        self.operation = operation
        self.elapsed_ms = elapsed_ms
        self.timeout_ms = timeout_ms
        super().__init__(
            f"Request budget exceeded for operation '{operation}': "
            f"{elapsed_ms:.2f}ms (limit: {timeout_ms}ms)"
        )


class PerformanceWarning:
    """Structured performance warning with context."""

    def __init__(
        self,
        operation: str,
        elapsed_ms: float,
        budget_type: str,
        context: dict | None = None,
        severity: str = "warning",
    ) -> None:
        """Initialize a performance warning.

        Args:
            operation: Name of the operation being measured.
            elapsed_ms: Elapsed time in milliseconds.
            budget_type: Either "startup" or "request".
            context: Additional context for structured logging.
            severity: Warning severity level.
        """
        self.operation = operation
        self.elapsed_ms = elapsed_ms
        self.budget_type = budget_type
        self.context = context or {}
        self.severity = severity
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        """Convert to dictionary for structured logging."""
        return {
            "operation": self.operation,
            "elapsed_ms": self.elapsed_ms,
            "budget_type": self.budget_type,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "context": self.context,
        }


async def run_bounded(
    operation: str,
    coroutine: Awaitable[T],
    warning_ms: float | None = None,
    timeout_ms: float | None = None,
    context: dict | None = None,
) -> T:
    """Execute a coroutine with bounded time and performance monitoring.

    Args:
        operation: Name of the operation for telemetry and error reporting.
        coroutine: The async coroutine to execute.
        warning_ms: Warning threshold in milliseconds (None = no warning).
        timeout_ms: Hard timeout in milliseconds (None = no timeout).
        context: Additional context for performance warnings.

    Returns:
        The result of the coroutine.

    Raises:
        StartupBudgetError: If startup budget is exceeded.
        RequestBudgetError: If request budget is exceeded.
        TimeoutError: If the coroutine times out.
    """
    if warning_ms is None:
        warning_ms = STARTUP_WARNING_MS if "startup" in operation else REQUEST_WARNING_MS
    if timeout_ms is None:
        timeout_ms = STARTUP_TIMEOUT_MS if "startup" in operation else REQUEST_TIMEOUT_MS

    start_time = time.monotonic()

    async def _execute_with_timeout() -> T:
        """Execute the coroutine with timeout."""
        if timeout_ms is None or timeout_ms <= 0:
            return await coroutine
        try:
            return await asyncio.wait_for(coroutine, timeout_ms / 1000.0)
        except TimeoutError:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                f"Operation '{operation}' timed out after {elapsed_ms:.2f}ms "
                f"(limit: {timeout_ms}ms)"
            )

            # Determine budget type and raise appropriate exception
            if "startup" in operation:
                raise StartupBudgetError(operation, elapsed_ms, timeout_ms) from None
            else:
                raise RequestBudgetError(operation, elapsed_ms, timeout_ms) from None

    async def _run_with_warning() -> T:
        """Execute with timeout and optional warning timer."""
        # Execute with timeout
        result = asyncio.create_task(_execute_with_timeout())

        # Check for warning threshold (only if timeout is positive)
        if timeout_ms is not None and timeout_ms > 0 and warning_ms < timeout_ms:
            async def _check_warning() -> None:
                """Emit a structured warning if the operation is still running."""
                await asyncio.sleep(warning_ms / 1000.0)
                if not result.done():
                    elapsed_ms = (time.monotonic() - start_time) * 1000
                    warning = PerformanceWarning(
                        operation=operation,
                        elapsed_ms=elapsed_ms,
                        budget_type="startup" if "startup" in operation else "request",
                        context=context,
                        severity="warning",
                    )
                    logger.warning(
                        f"Performance warning for '{operation}': {elapsed_ms:.2f}ms "
                        f"(warning threshold: {warning_ms}ms)",
                        extra={"performance_warning": warning.to_dict()},
                    )

            # Schedule warning check
            asyncio.create_task(_check_warning())

        # Wait for completion
        try:
            return await result
        except Exception:
            # Ensure the task is cancelled if we're handling an exception
            if not result.done():
                result.cancel()
            raise

    return await _run_with_warning()


def startup_budget(
    operation: str,
    warning_ms: float = STARTUP_WARNING_MS,
    timeout_ms: float = STARTUP_TIMEOUT_MS,
    context: dict | None = None,
) -> Callable:
    """Decorator for startup operations with performance budgets.

    Args:
        operation: Name of the startup operation.
        warning_ms: Warning threshold in milliseconds.
        timeout_ms: Hard timeout in milliseconds.
        context: Additional context for performance warnings.

    Returns:
        Decorator that wraps the function with budget enforcement.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: object, **kwargs: object) -> object:
            logger.info(f"Starting startup operation: {operation}")

            try:
                result = await run_bounded(
                    operation=operation,
                    coroutine=func(*args, **kwargs),
                    warning_ms=warning_ms,
                    timeout_ms=timeout_ms,
                    context=context,
                )
                logger.info(f"Startup operation completed: {operation}")
                return result
            except (TimeoutError, StartupBudgetError) as exc:
                logger.error(f"Startup operation failed: {operation} - {exc}")
                raise

        return wrapper

    return decorator


def request_budget(
    operation: str,
    warning_ms: float = REQUEST_WARNING_MS,
    timeout_ms: float = REQUEST_TIMEOUT_MS,
    context: dict | None = None,
) -> Callable:
    """Decorator for request operations with performance budgets.

    Args:
        operation: Name of the request operation.
        warning_ms: Warning threshold in milliseconds.
        timeout_ms: Hard timeout in milliseconds.
        context: Additional context for performance warnings.

    Returns:
        Decorator that wraps the function with budget enforcement.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: object, **kwargs: object) -> object:
            logger.info(f"Starting request operation: {operation}")

            try:
                result = await run_bounded(
                    operation=operation,
                    coroutine=func(*args, **kwargs),
                    warning_ms=warning_ms,
                    timeout_ms=timeout_ms,
                    context=context,
                )
                logger.info(f"Request operation completed: {operation}")
                return result
            except (TimeoutError, RequestBudgetError) as exc:
                logger.error(f"Request operation failed: {operation} - {exc}")
                raise

        return wrapper

    return decorator


class PerformanceBudgetManager:
    """Manager for performance budgets and telemetry."""

    def __init__(self) -> None:
        """Initialize empty warning and violation lists."""
        self._startup_warnings: list[PerformanceWarning] = []
        self._startup_violations: list[PerformanceWarning] = []
        self._request_warnings: list[PerformanceWarning] = []
        self._request_violations: list[PerformanceWarning] = []

    def record_warning(self, warning: PerformanceWarning) -> None:
        """Record a performance warning."""
        if warning.budget_type == "startup":
            self._startup_warnings.append(warning)
        else:
            self._request_warnings.append(warning)

        # Log structured warning
        logger.warning(f"Performance warning: {warning.to_dict()}")

    def record_violation(self, violation: PerformanceWarning) -> None:
        """Record a performance violation."""
        if violation.budget_type == "startup":
            self._startup_violations.append(violation)
        else:
            self._request_violations.append(violation)

        # Log structured violation
        logger.error(f"Performance violation: {violation.to_dict()}")

    def get_startup_warnings(self) -> list[PerformanceWarning]:
        """Get all startup performance warnings."""
        return self._startup_warnings.copy()

    def get_startup_violations(self) -> list[PerformanceWarning]:
        """Get all startup performance violations."""
        return self._startup_violations.copy()

    def get_request_warnings(self) -> list[PerformanceWarning]:
        """Get all request performance warnings."""
        return self._request_warnings.copy()

    def get_request_violations(self) -> list[PerformanceWarning]:
        """Get all request performance violations."""
        return self._request_violations.copy()

    def clear_all(self) -> None:
        """Clear all recorded warnings and violations."""
        self._startup_warnings.clear()
        self._startup_violations.clear()
        self._request_warnings.clear()
        self._request_violations.clear()


# Global performance budget manager
performance_budget_manager = PerformanceBudgetManager()


def get_performance_budget_manager() -> PerformanceBudgetManager:
    """Get the global performance budget manager."""
    return performance_budget_manager
