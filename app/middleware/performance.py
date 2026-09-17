"""Performance telemetry middleware and utilities."""
import os
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Monotonic clock captured at import, used only for high-resolution duration math.
_startup_monotonic = time.perf_counter()
# Wall-clock epoch seconds captured at import, exposed as the app startup time.
_startup_epoch = time.time()
_startup_duration = None

# Deployment identifier from environment, used to tag performance metrics.
_DEPLOYMENT_ID: str | None = os.getenv("VERCEL_DEPLOYMENT_ID") or os.getenv(
    "VERCEL_GIT_COMMIT_SHA",
)


class PerformanceMiddleware(BaseHTTPMiddleware):
    """Middleware that records request duration and adds X-Response-Time header.

    Also marks the first request as a cold start for metric purposes.
    """

    async def dispatch(self, request: Request, call_next):
        """Process a request, record duration, and attach performance headers.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler in the chain.

        Returns:
            Response with X-Response-Time and X-Server-Cold-Start headers.
        """
        from app.startup_diagnostics import next_request_snapshot
        snapshot = getattr(request.state, "startup_snapshot", None) or next_request_snapshot()
        start_ts = time.perf_counter()
        response: Response = await call_next(request)
        end_ts = time.perf_counter()
        duration_ms = (end_ts - start_ts) * 1000
        response.headers["X-Response-Time"] = str(round(duration_ms, 1))
        response.headers["X-Server-Cold-Start"] = "true" if snapshot.cold else "false"
        # Expose deployment ID on the request state for downstream metric recording
        request.state.deployment_id = _DEPLOYMENT_ID
        return response


async def compute_startup_duration() -> None:
    """Compute and store the application startup duration.

    Should be called once during the startup event after initialization completes.
    """
    global _startup_duration
    _startup_duration = time.perf_counter() - _startup_monotonic


def get_startup_time() -> float:
    """Return the UNIX epoch timestamp when the application process started."""
    return _startup_epoch


def get_startup_duration() -> float | None:
    """Return the startup duration in seconds, or None if not yet computed."""
    return _startup_duration
