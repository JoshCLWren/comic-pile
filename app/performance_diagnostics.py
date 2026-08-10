"""Per-request performance diagnostics for database and cache activity."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal

from app.cache import UpstashCache

logger = logging.getLogger(__name__)

CacheOutcome = Literal["hit", "miss", "write", "bypass", "timeout", "error"]
_DEFAULT_CACHE_OPERATION_TIMEOUT_SECONDS = 2.0


@dataclass
class RequestDiagnostics:
    """Mutable counters and context collected during one HTTP request."""

    request_id: str | None = None
    route: str | None = None
    cache_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_writes: int = 0
    cache_bypasses: int = 0
    cache_timeouts: int = 0
    cache_errors: int = 0
    cache_time_ms: float = 0.0
    database_queries: int = 0
    database_time_ms: float = 0.0

    @property
    def cache_status(self) -> str:
        """Return a compact aggregate cache status for response headers."""
        if self.cache_calls == 0:
            return "not-used"
        if self.cache_timeouts:
            return "timeout"
        if self.cache_errors:
            return "error"
        if self.cache_hits and self.cache_misses:
            return "mixed"
        if self.cache_hits:
            return "hit"
        if self.cache_misses:
            return "miss"
        if self.cache_writes:
            return "write"
        if self.cache_bypasses:
            return "bypass"
        return "unknown"


_request_diagnostics: ContextVar[RequestDiagnostics | None] = ContextVar(
    "request_diagnostics",
    default=None,
)


def begin_request_diagnostics(
    *,
    request_id: str | None = None,
    route: str | None = None,
) -> Token[RequestDiagnostics | None]:
    """Start a fresh diagnostics context for the current request.

    Args:
        request_id: Correlation identifier for the current HTTP request, when available.
        route: Request route associated with the diagnostics context, when available.

    Returns:
        ContextVar token used to restore the previous diagnostics context.
    """
    return _request_diagnostics.set(RequestDiagnostics(request_id=request_id, route=route))


def end_request_diagnostics(token: Token[RequestDiagnostics | None]) -> None:
    """Restore the diagnostics context that preceded the current request."""
    _request_diagnostics.reset(token)


def get_request_diagnostics() -> RequestDiagnostics:
    """Return the active diagnostics object or an empty detached snapshot."""
    return _request_diagnostics.get() or RequestDiagnostics()


def record_database_query(duration_ms: float) -> None:
    """Record one completed SQL query in the active request context."""
    diagnostics = _request_diagnostics.get()
    if diagnostics is None:
        return
    diagnostics.database_queries += 1
    diagnostics.database_time_ms += duration_ms


def record_cache_operation(outcome: CacheOutcome, duration_ms: float) -> None:
    """Record one cache operation and its result in the active request context."""
    diagnostics = _request_diagnostics.get()
    if diagnostics is None:
        return

    diagnostics.cache_calls += 1
    diagnostics.cache_time_ms += duration_ms

    if outcome == "hit":
        diagnostics.cache_hits += 1
    elif outcome == "miss":
        diagnostics.cache_misses += 1
    elif outcome == "write":
        diagnostics.cache_writes += 1
    elif outcome == "bypass":
        diagnostics.cache_bypasses += 1
    elif outcome == "timeout":
        diagnostics.cache_timeouts += 1
    else:
        diagnostics.cache_errors += 1


def _cache_operation_timeout_seconds() -> float:
    """Resolve the fail-open cache operation timeout from the environment."""
    raw_value = os.getenv("CACHE_OPERATION_TIMEOUT_SECONDS")
    if raw_value is None:
        return _DEFAULT_CACHE_OPERATION_TIMEOUT_SECONDS

    try:
        parsed = float(raw_value)
    except ValueError:
        logger.warning(
            "Invalid CACHE_OPERATION_TIMEOUT_SECONDS=%r; using %.1f seconds",
            raw_value,
            _DEFAULT_CACHE_OPERATION_TIMEOUT_SECONDS,
        )
        return _DEFAULT_CACHE_OPERATION_TIMEOUT_SECONDS

    if parsed <= 0:
        logger.warning(
            "CACHE_OPERATION_TIMEOUT_SECONDS must be positive; using %.1f seconds",
            _DEFAULT_CACHE_OPERATION_TIMEOUT_SECONDS,
        )
        return _DEFAULT_CACHE_OPERATION_TIMEOUT_SECONDS
    return parsed


def _record_cache_timeout_failure(cache: UpstashCache) -> None:
    """Feed wrapper-level timeouts into the cache circuit breaker when available."""
    breaker = getattr(cache, "_circuit_breaker", None)
    record_failure = getattr(breaker, "record_failure", None)
    if callable(record_failure):
        record_failure()


async def _await_cache_operation[T](
    operation: str,
    awaitable: Awaitable[T],
    fallback: T,
) -> tuple[T, bool]:
    """Await a cache operation with a fail-open timeout."""
    started_at = time.perf_counter()
    try:
        async with asyncio.timeout(_cache_operation_timeout_seconds()):
            return await awaitable, False
    except TimeoutError:
        duration_ms = (time.perf_counter() - started_at) * 1000
        record_cache_operation("timeout", duration_ms)
        logger.warning(
            "Cache %s timed out after %.2f ms; falling back",
            operation,
            duration_ms,
        )
        return fallback, True


def install_cache_instrumentation(cache: UpstashCache) -> None:
    """Wrap cache operations with timing, outcomes, and a fail-open timeout."""
    if getattr(cache, "_performance_instrumented", False):
        return

    original_get = cache.get
    original_set = cache.set
    original_delete = cache.delete
    original_clear_pattern = cache.clear_pattern

    async def instrumented_get(key: str) -> object | None:
        initialized = cache.is_initialized
        started_at = time.perf_counter()
        result, timed_out = await _await_cache_operation("get", original_get(key), None)
        if timed_out:
            _record_cache_timeout_failure(cache)
            return None

        duration_ms = (time.perf_counter() - started_at) * 1000
        if not initialized:
            record_cache_operation("bypass", duration_ms)
        elif result is None:
            record_cache_operation("miss", duration_ms)
        else:
            record_cache_operation("hit", duration_ms)
        return result

    async def instrumented_set(key: str, value: object, ttl: int | None = None) -> bool:
        initialized = cache.is_initialized
        started_at = time.perf_counter()
        result, timed_out = await _await_cache_operation(
            "set",
            original_set(key, value, ttl),
            False,
        )
        if timed_out:
            _record_cache_timeout_failure(cache)
            return False

        duration_ms = (time.perf_counter() - started_at) * 1000
        if not initialized:
            record_cache_operation("bypass", duration_ms)
        else:
            record_cache_operation("write" if result else "error", duration_ms)
        return result

    async def instrumented_delete(key: str) -> bool:
        initialized = cache.is_initialized
        started_at = time.perf_counter()
        result, timed_out = await _await_cache_operation(
            "delete",
            original_delete(key),
            False,
        )
        if timed_out:
            _record_cache_timeout_failure(cache)
            return False

        duration_ms = (time.perf_counter() - started_at) * 1000
        if not initialized:
            record_cache_operation("bypass", duration_ms)
        else:
            record_cache_operation("write" if result else "error", duration_ms)
        return result

    async def instrumented_clear_pattern(pattern: str) -> int:
        initialized = cache.is_initialized
        started_at = time.perf_counter()
        result, timed_out = await _await_cache_operation(
            "clear_pattern",
            original_clear_pattern(pattern),
            0,
        )
        if timed_out:
            _record_cache_timeout_failure(cache)
            return 0

        duration_ms = (time.perf_counter() - started_at) * 1000
        record_cache_operation("write" if initialized else "bypass", duration_ms)
        return result

    vars(cache).update(
        {
            "get": instrumented_get,
            "set": instrumented_set,
            "delete": instrumented_delete,
            "clear_pattern": instrumented_clear_pattern,
            "_performance_instrumented": True,
        }
    )
