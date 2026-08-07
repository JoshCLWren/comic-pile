"""Process-level startup and cold-request diagnostics.

The module is intentionally dependency-free so it can be imported early and adds
only a lock-protected counter plus monotonic clock reads to normal requests.
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
    """Immutable process-startup state attached to one request.

    Attributes:
        invocation: One-based request number handled by this process, or zero for startup events.
        cold: Whether this is the first request handled by this process.
        process_age_ms: Time since this module began loading.
        startup_complete: Whether the application startup hook completed.
        startup_duration_ms: Duration from module load through startup completion.
        deployment_id: Deployment or commit identifier when supplied by Vercel.
        process_started_at_ns: Wall-clock process marker for log correlation.
    """

    invocation: int
    cold: bool
    process_age_ms: float
    startup_complete: bool
    startup_duration_ms: float | None
    deployment_id: str | None
    process_started_at_ns: int


def mark_startup_complete() -> float:
    """Record application startup completion once and return its duration.

    Returns:
        Milliseconds elapsed since the startup diagnostics module loaded.
    """
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
    """Return process metadata for the startup event without consuming a request number."""
    return _snapshot(invocation=0, cold=False)


def next_request_snapshot() -> StartupSnapshot:
    """Advance the process request counter and return cold-start context.

    Returns:
        Snapshot identifying whether this is the process's first request.
    """
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
