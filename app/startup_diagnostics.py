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
    "VERCEL_GIT_COMMIT_SHA"
)
_lock = threading.Lock()
_request_count = 0
_startup_complete_at: float | None = None
_startup_duration_ms: float | None = None


@dataclass(frozen=True, slots=True)
class StartupSnapshot:
    """Immutable process-startup state for one startup or request event."""

    invocation: int
    cold: bool
    process_age_ms: float
    startup_complete: bool
    startup_duration_ms: float | None
    deployment_id: str | None
    process_started_at_ns: int


def mark_startup_complete() -> float:
    """Record application startup completion once and return its duration."""
    global _startup_complete_at, _startup_duration_ms

    with _lock:
        if _startup_complete_at is None:
            _startup_complete_at = time.perf_counter()
            _startup_duration_ms = (_startup_complete_at - _PROCESS_STARTED_AT) * 1000
        return _startup_duration_ms or 0.0


def _snapshot(*, invocation: int, cold: bool) -> StartupSnapshot:
    """Build a snapshot without mutating request state."""
    now = time.perf_counter()
    with _lock:
        startup_complete_at = _startup_complete_at
        startup_duration_ms = _startup_duration_ms

    return StartupSnapshot(
        invocation=invocation,
        cold=cold,
        process_age_ms=(now - _PROCESS_STARTED_AT) * 1000,
        startup_complete=startup_complete_at is not None,
        startup_duration_ms=startup_duration_ms,
        deployment_id=_DEPLOYMENT_ID,
        process_started_at_ns=_PROCESS_STARTED_AT_NS,
    )


def startup_event_snapshot() -> StartupSnapshot:
    """Return process metadata for startup logging without consuming a request number."""
    return _snapshot(invocation=0, cold=False)


def next_request_snapshot() -> StartupSnapshot:
    """Advance the process request counter and return cold-start context."""
    global _request_count

    with _lock:
        _request_count += 1
        invocation = _request_count

    return _snapshot(invocation=invocation, cold=invocation == 1)


def reset_startup_diagnostics_for_test() -> None:
    """Reset mutable process diagnostics for isolated unit tests."""
    global _request_count, _startup_complete_at, _startup_duration_ms

    with _lock:
        _request_count = 0
        _startup_complete_at = None
        _startup_duration_ms = None
