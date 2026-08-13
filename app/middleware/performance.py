"""Performance telemetry middleware and utilities."""
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Record application startup time in seconds (since epoch) and duration since import
_startup_time = time.perf_counter()
_startup_duration = None
_middleware_lock = False  # simple flag for cold start detection
_cold_start = True

class PerformanceMiddleware(BaseHTTPMiddleware):
    """Middleware that records request duration and adds X-Response-Time header.
    Also marks the first request as a cold start for metric purposes.
    """

    async def dispatch(self, request: Request, call_next):
        global _middleware_lock, _cold_start
        start_ts = time.perf_counter()
        response: Response = await call_next(request)
        end_ts = time.perf_counter()
        duration_ms = (end_ts - start_ts) * 1000
        response.headers["X-Response-Time"] = str(round(duration_ms, 1))
        if _cold_start:
            response.headers["X-Server-Cold-Start"] = "true"
            _cold_start = False
        else:
            response.headers["X-Server-Cold-Start"] = "false"
        return response


# Startup and shutdown hooks to compute startup duration
async def compute_startup_duration():
    global _startup_duration
    _startup_duration = time.perf_counter() - _startup_time

# Public API for metrics

def get_startup_time() -> float:
    """Return the UNIX epoch startup time for the app."""
    return _startup_time


def get_startup_duration() -> float | None:
    """Return the startup duration in seconds, or None if not yet computed."""
    return _startup_duration

# The below are used in the /api/metrics endpoint
# But compute_startup_duration will be called in startup event
