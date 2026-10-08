"""Performance budget enforcement and bounded await primitives."""

import asyncio
import time
from functools import wraps
from typing import Any, Callable, Optional

from app.config import get_settings
from app.logging import logger

# Performance budget constants (in milliseconds)
STARTUP_WARNING_MS = 2000
STARTUP_TIMEOUT_MS = 2500
REQUEST_WARNING_MS = 500
REQUEST_TIMEOUT_MS = 1000


class PerformanceBudgetError(Exception):
    """Base class for performance budget violations."""
    pass


class StartupBudgetExceeded(PerformanceBudgetError):
    """Raised when startup performance budget is exceeded."""
    
    def __init__(self, operation: str, elapsed_ms: float, timeout_ms: float):
        self.operation = operation
        self.elapsed_ms = elapsed_ms
        self.timeout_ms = timeout_ms
        super().__init__(
            f"Startup budget exceeded for operation '{operation}': "
            f"{elapsed_ms:.2f}ms (limit: {timeout_ms}ms)"
        )


class RequestBudgetExceeded(PerformanceBudgetError):
    """Raised when request performance budget is exceeded."""
    
    def __init__(self, route: str, elapsed_ms: float, timeout_ms: float):
        self.route = route
        self.elapsed_ms = elapsed_ms
        self.timeout_ms = timeout_ms
        super().__init__(
            f"Request budget exceeded for route '{route}': "
            f"{elapsed_ms:.2f}ms (limit: {timeout_ms}ms)"
        )


class PerformanceWarning:
    """Structured performance warning with context."""
    
    def __init__(
        self,
        operation: str,
        elapsed_ms: float,
        budget_type: str,
        context: Optional[dict] = None,
        severity: str = "warning"
    ):
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


def run_bounded(
    operation: str,
    coroutine: Any,
    warning_ms: Optional[float] = None,
    timeout_ms: Optional[float] = None,
    context: Optional[dict] = None,
) -> Any:
    """
    Execute a coroutine with bounded time and performance monitoring.
    
    Args:
        operation: Name of the operation for telemetry and error reporting
        coroutine: The async coroutine to execute
        warning_ms: Warning threshold in milliseconds (None = no warning)
        timeout_ms: Hard timeout in milliseconds (None = no timeout)
        context: Additional context for performance warnings
    
    Returns:
        The result of the coroutine
    
    Raises:
        StartupBudgetExceeded: If startup budget is exceeded
        RequestBudgetExceeded: If request budget is exceeded
        asyncio.TimeoutError: If the coroutine times out
    """
    # Use defaults if not specified
    if warning_ms is None:
        warning_ms = STARTUP_WARNING_MS if "startup" in operation else REQUEST_WARNING_MS
    if timeout_ms is None:
        timeout_ms = STARTUP_TIMEOUT_MS if "startup" in operation else REQUEST_TIMEOUT_MS
    
    start_time = time.monotonic()
    
    async def _execute_with_timeout():
        """Execute the coroutine with timeout."""
        try:
            return await asyncio.wait_for(coroutine, timeout_ms / 1000.0)
        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                f"Operation '{operation}' timed out after {elapsed_ms:.2f}ms "
                f"(limit: {timeout_ms}ms)"
            )
            
            # Determine budget type and raise appropriate exception
            if "startup" in operation:
                raise StartupBudgetExceeded(operation, elapsed_ms, timeout_ms)
            else:
                raise RequestBudgetExceeded(operation, elapsed_ms, timeout_ms)
    
    try:
        # Execute with timeout
        result = asyncio.create_task(_execute_with_timeout())
        
        # Check for warning threshold
        if warning_ms < timeout_ms:
            async def _check_warning():
                await asyncio.sleep(warning_ms / 1000.0)
                if not result.done():
                    elapsed_ms = (time.monotonic() - start_time) * 1000
                    warning = PerformanceWarning(
                        operation=operation,
                        elapsed_ms=elapsed_ms,
                        budget_type="startup" if "startup" in operation else "request",
                        context=context,
                        severity="warning"
                    )
                    logger.warning(
                        f"Performance warning for '{operation}': {elapsed_ms:.2f}ms "
                        f"(warning threshold: {warning_ms}ms) - {warning.to_dict()}"
                    )
            
            # Schedule warning check
            asyncio.create_task(_check_warning())
        
        # Wait for completion
        return await result
    
    except Exception as e:
        # Ensure the task is cancelled if we're handling an exception
        if not result.done():
            result.cancel()
        raise


def startup_budget(
    operation: str,
    warning_ms: float = STARTUP_WARNING_MS,
    timeout_ms: float = STARTUP_TIMEOUT_MS,
    context: Optional[dict] = None,
):
    """
    Decorator for startup operations with performance budgets.
    
    Args:
        operation: Name of the startup operation
        warning_ms: Warning threshold in milliseconds
        timeout_ms: Hard timeout in milliseconds
        context: Additional context for performance warnings
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger.info(f"Starting startup operation: {operation}")
            
            try:
                result = await run_bounded(
                    operation=operation,
                    coroutine=func(*args, **kwargs),
                    warning_ms=warning_ms,
                    timeout_ms=timeout_ms,
                    context=context
                )
                logger.info(f"Startup operation completed: {operation}")
                return result
            except (StartupBudgetExceeded, asyncio.TimeoutError) as e:
                logger.error(f"Startup operation failed: {operation} - {e}")
                raise
        return wrapper
    return decorator


def request_budget(
    operation: str,
    warning_ms: float = REQUEST_WARNING_MS,
    timeout_ms: float = REQUEST_TIMEOUT_MS,
    context: Optional[dict] = None,
):
    """
    Decorator for request operations with performance budgets.
    
    Args:
        operation: Name of the request operation
        warning_ms: Warning threshold in milliseconds
        timeout_ms: Hard timeout in milliseconds
        context: Additional context for performance warnings
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger.info(f"Starting request operation: {operation}")
            
            try:
                result = await run_bounded(
                    operation=operation,
                    coroutine=func(*args, **kwargs),
                    warning_ms=warning_ms,
                    timeout_ms=timeout_ms,
                    context=context
                )
                logger.info(f"Request operation completed: {operation}")
                return result
            except (RequestBudgetExceeded, asyncio.TimeoutError) as e:
                logger.error(f"Request operation failed: {operation} - {e}")
                raise
        return wrapper
    return decorator


class PerformanceBudgetManager:
    """Manager for performance budgets and telemetry."""
    
    def __init__(self):
        self._startup_warnings = []
        self._startup_violations = []
        self._request_warnings = []
        self._request_violations = []
    
    def record_warning(self, warning: PerformanceWarning) -> None:
        """Record a performance warning."""
        if warning.budget_type == "startup":
            self._startup_warnings.append(warning)
        else:
            self._request_warnings.append(wwarning)
        
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