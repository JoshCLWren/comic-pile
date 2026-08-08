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
_DEPLOYMENT_ID: Final[str | None] = os.getenv("VERCEL_DEPLOYMENT_ID") or os.getenv(
    "VERCEL_GIT_COMMIT_SHA",
)
_lock = threading.Lock()
_request_count = 0
_application_import_complete_at: float | None = None
_application_created_at: float | None = None
_startup_complete_at: float | None = None


@dataclass(frozen=True, slots=True)
class StartupSnapshot:
    """Immutable process-startup state for one startup or request event."""

    invocation: int
    cold: bool
    process_age_ms: float
    startup_complete: bool
    startup_duration_ms: float | None
    application_import_ms: float | None
    application_creation_ms: float | None
    lifespan_ms: float | None
    deployment_id: str | None
    process_started_at_ns: int


def mark_application_import_complete() -> None:
    """Mark completion of imports needed to reach the application factory."""
    global _application_import_complete_at

    with _lock:
        if _application_import_complete_at is None:
            _application_import_complete_at = time.perf_counter()


def mark_application_created() -> None:
    """Mark completion of FastAPI application creation."""
    global _application_created_at

    with _lock:
        if _application_created_at is None:
            _application_created_at = time.perf_counter()


def mark_startup_complete() -> float:
    """Record lifespan startup completion once.

    Returns:
        Total measured startup duration in milliseconds.
    """
    global _startup_complete_at

    with _lock:
        if _startup_complete_at is None:
            _startup_complete_at = time.perf_counter()
        return (_startup_complete_at - _PROCESS_STARTED_AT) * 1000


def _duration_ms(start: float | None, end: float | None) -> float | None:
    """Return a duration in milliseconds when both phase boundaries are known."""
    if start is None or end is None:
        return None
    return (end - start) * 1000


def _snapshot(*, invocation: int, cold: bool) -> StartupSnapshot:
    """Build a snapshot without mutating request state."""
    with _lock:
        now = time.perf_counter()
        import_complete_at = _application_import_complete_at
        application_created_at = _application_created_at
        startup_complete_at = _startup_complete_at

    return StartupSnapshot(
        invocation=invocation,
        cold=cold,
        process_age_ms=(now - _PROCESS_STARTED_AT) * 1000,
        startup_complete=startup_complete_at is not None,
        startup_duration_ms=_duration_ms(_PROCESS_STARTED_AT, startup_complete_at),
        application_import_ms=_duration_ms(_PROCESS_STARTED_AT, import_complete_at),
        application_creation_ms=_duration_ms(import_complete_at, application_created_at),
        lifespan_ms=_duration_ms(application_created_at, startup_complete_at),
        deployment_id=_DEPLOYMENT_ID,
        process_started_at_ns=_PROCESS_STARTED_AT_NS,
    )


def startup_event_snapshot() -> StartupSnapshot:
    """Return process metadata for startup logging without consuming a request number.

    Returns:
        StartupSnapshot for the current process startup state.
    """
    return _snapshot(invocation=0, cold=False)


def next_request_snapshot() -> StartupSnapshot:
    """Advance the process request counter and return cold-start context.

    Returns:
        StartupSnapshot after incrementing the process invocation count.
    """
    global _request_count

    with _lock:
        _request_count += 1
        invocation = _request_count

    return _snapshot(invocation=invocation, cold=invocation == 1)


def reset_startup_diagnostics_for_test() -> None:
    """Reset mutable process diagnostics for isolated unit tests."""
    global _request_count, _application_import_complete_at, _application_created_at
    global _startup_complete_at

    with _lock:
        _request_count = 0
        _application_import_complete_at = None
        _application_created_at = None
        _startup_complete_at = None
