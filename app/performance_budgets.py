"""Performance budget enforcement and bounded await primitives.

The frozen production contract this module implements (issue #3243):

- Total ping-ready startup: ``STARTUP_WARNING_MS`` warning, ``STARTUP_TIMEOUT_MS``
  hard budget.
- Ordinary warm interactive requests: ``REQUEST_WARNING_MS`` warning,
  ``REQUEST_TIMEOUT_MS`` violation.
- Every readiness-critical await runs through :func:`run_bounded` with an
  operation-specific warning budget and hard deadline that is materially smaller
  than the total startup budget.

Budgets are never relaxed automatically, and a hard deadline is never silently
turned into an unbounded await.
"""

import asyncio
import logging
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from functools import wraps

logger = logging.getLogger(__name__)

# Performance budget constants (in milliseconds)
STARTUP_WARNING_MS = 2000
STARTUP_TIMEOUT_MS = 2500
REQUEST_WARNING_MS = 500
REQUEST_TIMEOUT_MS = 1000

# Retention ceiling for recorded warnings/violations. Budget telemetry must stay
# queryable for repeated offenders without growing for the life of the process.
MAX_TRACKED_EVENTS = 256


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


def budget_type_for(operation: str) -> str:
    """Classify an operation as startup-critical or request-scoped.

    Args:
        operation: Operation name used for telemetry and classification.

    Returns:
        Either "startup" or "request".
    """
    return "startup" if "startup" in operation else "request"


def _budget_error(budget_type: str, operation: str, elapsed_ms: float, timeout_ms: float) -> Exception:
    """Build the budget error matching a budget type.

    Args:
        budget_type: Either "startup" or "request".
        operation: Operation that exceeded its deadline.
        elapsed_ms: Measured elapsed time in milliseconds.
        timeout_ms: Configured hard deadline in milliseconds.

    Returns:
        StartupBudgetError or RequestBudgetError.
    """
    if budget_type == "startup":
        return StartupBudgetError(operation, elapsed_ms, timeout_ms)
    return RequestBudgetError(operation, elapsed_ms, timeout_ms)


async def _emit_warning_when_slow(
    operation: str,
    budget_type: str,
    finished: asyncio.Event,
    warning_ms: float,
    started_at: float,
    context: dict | None,
) -> None:
    """Record and log one structured warning when an operation runs long.

    Args:
        operation: Operation name used for telemetry.
        budget_type: Either "startup" or "request".
        finished: Event set once the bounded operation settles.
        warning_ms: Warning threshold in milliseconds.
        started_at: Monotonic timestamp captured before the operation started.
        context: Additional structured logging context.

    Returns:
        None.
    """
    with suppress(TimeoutError):
        await asyncio.wait_for(finished.wait(), warning_ms / 1000.0)
        return
    if finished.is_set():
        return
    elapsed_ms = (time.monotonic() - started_at) * 1000
    warning = PerformanceWarning(
        operation=operation,
        elapsed_ms=elapsed_ms,
        budget_type=budget_type,
        context=context,
        severity="warning",
    )
    get_performance_budget_manager().record_warning(warning)
    logger.warning(
        f"Performance warning for '{operation}': {elapsed_ms:.2f}ms "
        f"(warning threshold: {warning_ms}ms)",
        extra={"performance_warning": warning.to_dict()},
    )


async def run_bounded[T](
    operation: str,
    coroutine: Awaitable[T],
    warning_ms: float | None = None,
    timeout_ms: float | None = None,
    context: dict | None = None,
) -> T:
    """Execute a coroutine with a bounded deadline and performance telemetry.

    The awaited coroutine is driven inline, so an outer cancellation and the
    deadline both propagate into it instead of leaving an abandoned background
    task behind.

    Args:
        operation: Name of the operation for telemetry and error reporting.
        coroutine: The async coroutine to execute.
        warning_ms: Warning threshold in milliseconds (None = budget default).
        timeout_ms: Hard deadline in milliseconds (None = budget default).
        context: Additional context for performance warnings.

    Returns:
        The result of the coroutine.

    Raises:
        ValueError: If the resolved hard deadline is not positive.
        StartupBudgetError: If a startup budget deadline is exceeded.
        RequestBudgetError: If a request budget deadline is exceeded.
    """
    budget_type = budget_type_for(operation)
    if warning_ms is None:
        warning_ms = STARTUP_WARNING_MS if budget_type == "startup" else REQUEST_WARNING_MS
    if timeout_ms is None:
        timeout_ms = STARTUP_TIMEOUT_MS if budget_type == "startup" else REQUEST_TIMEOUT_MS
    if timeout_ms <= 0:
        raise ValueError(
            f"run_bounded requires a positive hard deadline; got timeout_ms={timeout_ms} "
            f"for operation '{operation}'"
        )

    manager = get_performance_budget_manager()
    started_at = time.monotonic()
    finished = asyncio.Event()
    warning_task: asyncio.Task[None] | None = None
    if 0 < warning_ms < timeout_ms:
        warning_task = asyncio.create_task(
            _emit_warning_when_slow(
                operation=operation,
                budget_type=budget_type,
                finished=finished,
                warning_ms=warning_ms,
                started_at=started_at,
                context=context,
            )
        )

    try:
        async with asyncio.timeout(timeout_ms / 1000.0) as deadline:
            return await coroutine
    except TimeoutError:
        if not deadline.expired():
            # The awaited operation raised its own TimeoutError; that is an
            # operation failure, not a breach of this budget.
            raise
        elapsed_ms = (time.monotonic() - started_at) * 1000
        violation = PerformanceWarning(
            operation=operation,
            elapsed_ms=elapsed_ms,
            budget_type=budget_type,
            context={**(context or {}), "deadline_ms": timeout_ms},
            severity="violation",
        )
        manager.record_violation(violation)
        logger.error(
            f"Operation '{operation}' exceeded its hard budget: {elapsed_ms:.2f}ms "
            f"(deadline: {timeout_ms}ms)",
            extra={"performance_violation": violation.to_dict()},
        )
        raise _budget_error(budget_type, operation, elapsed_ms, timeout_ms) from None
    finally:
        finished.set()
        if warning_task is not None:
            warning_task.cancel()
            with suppress(asyncio.CancelledError):
                await warning_task


def evaluate_startup_budget(
    elapsed_ms: float,
    *,
    operation: str = "startup.readiness",
    context: dict | None = None,
) -> PerformanceWarning | None:
    """Record and log the startup budget verdict for a measured startup duration.

    Args:
        elapsed_ms: Measured ping-ready startup duration in milliseconds.
        operation: Operation name used for telemetry.
        context: Additional structured logging context.

    Returns:
        The recorded warning or violation, or None when inside budget.
    """
    manager = get_performance_budget_manager()
    if elapsed_ms >= STARTUP_TIMEOUT_MS:
        violation = PerformanceWarning(
            operation=operation,
            elapsed_ms=elapsed_ms,
            budget_type="startup",
            context={**(context or {}), "deadline_ms": STARTUP_TIMEOUT_MS},
            severity="violation",
        )
        manager.record_violation(violation)
        logger.error(
            "Startup hard budget exceeded for '%s': %.2f ms (limit: %d ms)",
            operation,
            elapsed_ms,
            STARTUP_TIMEOUT_MS,
            extra={
                "event": "startup_performance_violation",
                "level": "ERROR",
                "startup_duration_ms": round(elapsed_ms, 2),
                "performance_violation": violation.to_dict(),
            },
        )
        return violation
    if elapsed_ms >= STARTUP_WARNING_MS:
        warning = PerformanceWarning(
            operation=operation,
            elapsed_ms=elapsed_ms,
            budget_type="startup",
            context={**(context or {}), "warning_budget_ms": STARTUP_WARNING_MS},
            severity="warning",
        )
        manager.record_warning(warning)
        logger.warning(
            "Startup performance warning for '%s': %.2f ms (warning threshold: %d ms)",
            operation,
            elapsed_ms,
            STARTUP_WARNING_MS,
            extra={
                "event": "startup_performance_warning",
                "level": "WARNING",
                "startup_duration_ms": round(elapsed_ms, 2),
                "performance_warning": warning.to_dict(),
            },
        )
        return warning
    return None


def enforce_startup_budget(
    elapsed_ms: float,
    *,
    environment: str,
    operation: str = "startup.readiness",
    context: dict | None = None,
) -> PerformanceWarning | None:
    """Evaluate the total ping-ready startup budget and fail production startup.

    Production fails initialization when the hard budget is crossed so a
    pathological process fails attributable instead of serving toward a
    multi-second cold start. Other environments record and log the violation and
    continue, because a slow developer machine or a loaded test runner is not a
    production startup regression.

    Args:
        elapsed_ms: Measured ping-ready startup duration in milliseconds.
        environment: Current application environment.
        operation: Operation name used for telemetry.
        context: Additional structured logging context.

    Returns:
        The recorded warning or violation, or None when inside budget.

    Raises:
        StartupBudgetError: In production when the hard startup budget is crossed.
    """
    recorded = evaluate_startup_budget(elapsed_ms, operation=operation, context=context)
    if recorded is not None and recorded.severity == "violation" and environment == "production":
        raise StartupBudgetError(operation, recorded.elapsed_ms, STARTUP_TIMEOUT_MS)
    return recorded


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
    """Bounded recorder for performance warnings and violations.

    Recorded events are queryable per operation so repeated offenders can be
    turned into actionable performance work, and retention is capped so a slow
    route cannot grow process memory without bound.
    """

    def __init__(self, *, max_tracked_events: int = MAX_TRACKED_EVENTS) -> None:
        """Initialize empty bounded warning and violation buffers.

        Args:
            max_tracked_events: Maximum retained events per budget category.
        """
        self._startup_warnings: deque[PerformanceWarning] = deque(maxlen=max_tracked_events)
        self._startup_violations: deque[PerformanceWarning] = deque(maxlen=max_tracked_events)
        self._request_warnings: deque[PerformanceWarning] = deque(maxlen=max_tracked_events)
        self._request_violations: deque[PerformanceWarning] = deque(maxlen=max_tracked_events)
        self._warning_counts: Counter[str] = Counter()
        self._violation_counts: Counter[str] = Counter()

    def record_warning(self, warning: PerformanceWarning) -> None:
        """Record a performance warning.

        Args:
            warning: Warning to retain and count.

        Returns:
            None.
        """
        if warning.budget_type == "startup":
            self._startup_warnings.append(warning)
        else:
            self._request_warnings.append(warning)
        self._warning_counts[warning.operation] += 1

    def record_violation(self, violation: PerformanceWarning) -> None:
        """Record a performance violation.

        Args:
            violation: Violation to retain and count.

        Returns:
            None.
        """
        if violation.budget_type == "startup":
            self._startup_violations.append(violation)
        else:
            self._request_violations.append(violation)
        self._violation_counts[violation.operation] += 1

    def get_startup_warnings(self) -> list[PerformanceWarning]:
        """Get retained startup performance warnings.

        Returns:
            Retained startup warnings, oldest first.
        """
        return list(self._startup_warnings)

    def get_startup_violations(self) -> list[PerformanceWarning]:
        """Get retained startup performance violations.

        Returns:
            Retained startup violations, oldest first.
        """
        return list(self._startup_violations)

    def get_request_warnings(self) -> list[PerformanceWarning]:
        """Get retained request performance warnings.

        Returns:
            Retained request warnings, oldest first.
        """
        return list(self._request_warnings)

    def get_request_violations(self) -> list[PerformanceWarning]:
        """Get retained request performance violations.

        Returns:
            Retained request violations, oldest first.
        """
        return list(self._request_violations)

    def warning_counts_by_operation(self) -> dict[str, int]:
        """Get warning totals per operation across the whole process lifetime.

        Returns:
            Operation name to warning count.
        """
        return dict(self._warning_counts)

    def violation_counts_by_operation(self) -> dict[str, int]:
        """Get violation totals per operation across the whole process lifetime.

        Returns:
            Operation name to violation count.
        """
        return dict(self._violation_counts)

    def clear_all(self) -> None:
        """Clear all recorded warnings and violations.

        Returns:
            None.
        """
        self._startup_warnings.clear()
        self._startup_violations.clear()
        self._request_warnings.clear()
        self._request_violations.clear()
        self._warning_counts.clear()
        self._violation_counts.clear()


# Global performance budget manager
performance_budget_manager = PerformanceBudgetManager()


def get_performance_budget_manager() -> PerformanceBudgetManager:
    """Get the global performance budget manager.

    Returns:
        The process-wide performance budget manager.
    """
    return performance_budget_manager