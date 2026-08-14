"""Performance telemetry middleware and utilities."""
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Monotonic clock captured at import, used only for high-resolution duration math.
_startup_monotonic = time.perf_counter()
# Wall-clock epoch seconds captured at import, exposed as the app startup time.
_startup_epoch = time.time()
_startup_duration = None
# _middleware_lock is deprecated; use startup_diagnostics for cold start detection
# _cold_start is deprecated; cold start detection now handled by startup_diagnostics

class PerformanceMiddleware(BaseHTTPMiddleware):
    """Middleware that records request duration and adds X-Response-Time header.
    Also marks the first request as a cold start for metric purposes.
    """

    async def dispatch(self, request: Request, call_next):
        from app.startup_diagnostics import next_request_snapshot
        snapshot = next_request_snapshot()
        start_ts = time.perf_counter()
        response: Response = await call_next(request)
        end_ts = time.perf_counter()
        duration_ms = (end_ts - start_ts) * 1000
        response.headers["X-Response-Time"] = str(round(duration_ms, 1))
        response.headers["X-Server-Cold-Start"] = "true" if snapshot.cold else "false"
        return response


# Startup and shutdown hooks to compute startup duration
async def compute_startup_duration():
    global _startup_duration
    _startup_duration = time.perf_counter() - _startup_monotonic

# Public API for metrics

def get_startup_time() -> float:
    """Return the UNIX epoch startup time for the app."""
    return _startup_epoch


def get_startup_duration() -> float | None:
    """Return the startup duration in seconds, or None if not yet computed."""
    return _startup_duration

# The below are used in the /api/metrics endpoint
# But compute_startup_duration will be called in startup event
