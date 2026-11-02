"""Process-level startup and cold-request diagnostics.

The module is intentionally dependency-free so the Vercel entry point can import
it before the rest of the application. Normal requests pay only a lock-protected
counter increment and monotonic clock read.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Final

_PROCESS_STARTED_AT: Final[float] = time.perf_counter()
_PROCESS_STARTED_AT_NS: Final[int] = time.time_ns()
_PROCESS_STARTED_CPU: Final[float] = time.process_time()
_DEPLOYMENT_ID: Final[str | None] = os.getenv("VERCEL_DEPLOYMENT_ID") or os.getenv(
    "VERCEL_GIT_COMMIT_SHA",
)
_lock = threading.Lock()
_request_count = 0
_application_import_complete_at: float | None = None
_application_created_at: float | None = None
_lifespan_started_at: float | None = None
_startup_complete_at: float | None = None
_startup_complete_cpu: float | None = None
_heavy_init_started_at: float | None = None
_heavy_init_complete_at: float | None = None


@dataclass(frozen=True, slots=True)
class StartupSnapshot:
    """Immutable process-startup state for one startup or request event."""

    invocation: int
    cold: bool
    process_age_ms: float
    process_to_startup_ms: float | None
    startup_cpu_ms: float | None
    startup_complete: bool
    startup_duration_ms: float | None
    application_import_ms: float | None
    application_creation_ms: float | None
    lifespan_ms: float | None
    heavy_initialized: bool
    heavy_init_duration_ms: float | None
    heavy_init_process_age_ms: float | None
    deployment_id: str | None
    process_started_at_ns: int


def mark_application_import_complete() -> None:
    """Mark completion of imports needed to reach the application factory.

    Args:
        None.

    Returns:
        None.
    """
    global _application_import_complete_at

    with _lock:
        if _application_import_complete_at is None:
            _application_import_complete_at = time.perf_counter()


def mark_application_created() -> None:
    """Mark completion of FastAPI application creation.

    Args:
        None.

    Returns:
        None.
    """
    global _application_created_at

    with _lock:
        if _application_created_at is None:
            _application_created_at = time.perf_counter()


def mark_lifespan_started() -> None:
    """Mark the beginning of lifespan startup work, excluding pre-lifespan idle age."""
    global _lifespan_started_at

    with _lock:
        if _lifespan_started_at is None:
            _lifespan_started_at = time.perf_counter()


def mark_startup_complete() -> float:
    """Record lifespan startup completion once.

    Args:
        None.

    Returns:
        Measured startup work in milliseconds, excluding inter-phase idle time.
    """
    global _startup_complete_at, _startup_complete_cpu

    with _lock:
        if _startup_complete_at is None:
            _startup_complete_at = time.perf_counter()
            _startup_complete_cpu = time.process_time()
    return startup_event_snapshot().startup_duration_ms or 0.0


def _duration_ms(start: float | None, end: float | None) -> float | None:
    """Return a duration in milliseconds when both phase boundaries are known."""
    if start is None or end is None:
        return None
    return (end - start) * 1000


def mark_heavy_init_started() -> None:
    """Mark the actual beginning of deferred database initialization."""
    global _heavy_init_started_at

    with _lock:
        if _heavy_init_started_at is None:
            _heavy_init_started_at = time.perf_counter()


def mark_heavy_init_complete() -> float:
    """Record heavy initialization completion once.

    Heavy init covers database connectivity that the lightweight ping wake-up
    intentionally skips.

    Returns:
        Deferred initialization duration, not the age of the process.
    """
    global _heavy_init_complete_at

    with _lock:
        if _heavy_init_complete_at is None:
            _heavy_init_complete_at = time.perf_counter()
        return _duration_ms(_heavy_init_started_at, _heavy_init_complete_at) or 0.0


def is_heavy_initialized() -> bool:
    """Return whether heavy initialization has completed.

    Returns:
        True when heavy init has finished at least once.
    """
    with _lock:
        return _heavy_init_complete_at is not None


def _snapshot(*, invocation: int, cold: bool) -> StartupSnapshot:
    """Build a snapshot without mutating request state."""
    with _lock:
        now = time.perf_counter()
        import_complete_at = _application_import_complete_at
        application_created_at = _application_created_at
        lifespan_started_at = _lifespan_started_at
        startup_complete_at = _startup_complete_at
        startup_complete_cpu = _startup_complete_cpu
        heavy_init_started_at = _heavy_init_started_at
        heavy_init_complete_at = _heavy_init_complete_at

    # Sum measured startup phases, not the interval from module import to
    # lifespan completion: a Vercel worker may sit idle between those phases.
    import_ms = _duration_ms(_PROCESS_STARTED_AT, import_complete_at)
    creation_ms = _duration_ms(import_complete_at, application_created_at)
    lifespan_ms = _duration_ms(lifespan_started_at, startup_complete_at)
    phases = (import_ms, creation_ms, lifespan_ms)
    startup_work_ms = sum(value for value in phases if value is not None)
    if startup_complete_at is None or not any(value is not None for value in phases):
        startup_work_ms = None

    return StartupSnapshot(
        invocation=invocation,
        cold=cold,
        process_age_ms=(now - _PROCESS_STARTED_AT) * 1000,
        process_to_startup_ms=_duration_ms(_PROCESS_STARTED_AT, startup_complete_at),
        startup_cpu_ms=(
            (startup_complete_cpu - _PROCESS_STARTED_CPU) * 1000
            if startup_complete_cpu is not None
            else None
        ),
        startup_complete=startup_complete_at is not None,
        startup_duration_ms=startup_work_ms,
        application_import_ms=import_ms,
        application_creation_ms=creation_ms,
        lifespan_ms=lifespan_ms,
        heavy_initialized=heavy_init_complete_at is not None,
        heavy_init_duration_ms=_duration_ms(heavy_init_started_at, heavy_init_complete_at),
        heavy_init_process_age_ms=_duration_ms(_PROCESS_STARTED_AT, heavy_init_complete_at),
        deployment_id=_DEPLOYMENT_ID,
        process_started_at_ns=_PROCESS_STARTED_AT_NS,
    )


def startup_event_snapshot() -> StartupSnapshot:
    """Return process metadata for startup logging without consuming a request number.

    Args:
        None.

    Returns:
        StartupSnapshot for the current process startup state.
    """
    return _snapshot(invocation=0, cold=False)


def next_request_snapshot() -> StartupSnapshot:
    """Advance the process request counter and return cold-start context.

    Args:
        None.

    Returns:
        StartupSnapshot after incrementing the process invocation count.
    """
    global _request_count

    with _lock:
        _request_count += 1
        invocation = _request_count

    return _snapshot(invocation=invocation, cold=invocation == 1)


def reset_startup_diagnostics_for_test() -> None:
    """Reset mutable process diagnostics for isolated unit tests.

    Args:
        None.

    Returns:
        None.
    """
    global _request_count, _application_import_complete_at, _application_created_at
    global _lifespan_started_at, _startup_complete_at, _startup_complete_cpu
    global _heavy_init_started_at, _heavy_init_complete_at

    with _lock:
        _request_count = 0
        _application_import_complete_at = None
        _application_created_at = None
        _lifespan_started_at = None
        _startup_complete_at = None
        _startup_complete_cpu = None
        _heavy_init_started_at = None
        _heavy_init_complete_at = None
