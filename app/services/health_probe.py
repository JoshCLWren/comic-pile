"""Health probe business logic and orchestration.

Services own business rules, transaction boundaries, and error handling.
Query construction lives in ``app/repositories/health_repository.py``.
"""

import asyncio
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from app.cache import cache
from app.repositories import health_repository
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEPENDENCY_TIMEOUT_SECONDS = 2.0

_instance_id: str | None = None


def _get_instance_id() -> str:
    """Get or create a stable instance ID for process lifetime.

    This ID is created once at module import and persists for the process lifetime,
    allowing Vercel to measure instance reuse across requests.

    Returns:
        A stable instance identifier string.
    """
    global _instance_id
    if _instance_id is None:
        _instance_id = f"instance-{secrets.token_urlsafe(8)}"
    return _instance_id


class ProbeError(Exception):
    """Base exception for probe failures."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        """Initialize the probe error.

        Args:
            message: Human-readable error description.
            cause: Optional underlying exception that caused this error.
        """
        super().__init__(message)
        self.cause = cause


class ProbeTimeoutError(ProbeError):
    """Raised when a probe times out."""


class ProbeUnavailableError(ProbeError):
    """Raised when a probe target is unavailable."""


class ProbeNotConfiguredError(ProbeError):
    """Raised when a probe target is not configured."""


@dataclass(slots=True)
class DependencyProbeResult:
    """One bounded dependency probe result."""

    status: Literal["healthy", "unavailable", "timeout", "not_configured"]
    duration_ms: float


@dataclass(slots=True)
class DependencyHealthResult:
    """Operational dependency-health result without sensitive metadata."""

    status: Literal["healthy", "degraded", "unhealthy"]
    database: DependencyProbeResult
    cache: DependencyProbeResult
    total_duration_ms: float


@dataclass(slots=True)
class CacheQuotaHealthResult:
    """Visible cache-quota snapshot for budget alerting."""

    status: Literal["ok", "near-limit", "over-budget"]
    observed_commands: int
    budget: int
    remaining: int
    usage_ratio: float
    alerted: bool
    throttling: bool
    degraded: bool = False


@dataclass(slots=True)
class WarmInstanceDiagnostics:
    """Instance-level diagnostics for Vercel warm endpoint."""

    instance_id: str
    process_start_time_ns: int
    request_count: int
    startup_time_ms: float | None = None
    process_age_ms: float | None = None


@dataclass(slots=True)
class WarmEndpointResult:
    """Result from the warm endpoint for instance reuse tracking."""

    status: Literal["warming", "cold", "no_activity"]
    instance: WarmInstanceDiagnostics
    has_active_session: bool
    request_count_today: int


def _get_heartbeat_max_requests() -> int:
    """Get the maximum requests allowed per day for the warm endpoint."""
    import os

    raw_value = os.getenv("WARM_ENDPOINT_MAX_DAILY_REQUESTS", "1000")
    try:
        return max(1, min(10000, int(raw_value)))
    except ValueError:
        return 1000


def _get_inactivity_threshold_seconds() -> int:
    """Get the inactivity threshold in seconds for stopping heartbeats."""
    import os

    raw_value = os.getenv("WARM_ENDPOINT_INACTIVITY_SECONDS", "1800")
    try:
        return max(60, min(86400, int(raw_value)))
    except ValueError:
        return 1800


def _is_warm_endpoint_enabled() -> bool:
    """Check if the warm endpoint is enabled."""
    import os

    return os.getenv("WARM_ENDPOINT_ENABLED", "false").lower() == "true"


def _is_heartbeat_within_limits(request_count: int) -> bool:
    """Check if the heartbeat is within the daily request limit."""
    return request_count <= _get_heartbeat_max_requests()


def _overall_status(
    database: DependencyProbeResult,
    cache_probe: DependencyProbeResult,
) -> Literal["healthy", "degraded", "unhealthy"]:
    """Derive the aggregate status from independent probe results.

    Args:
        database: Database probe result.
        cache_probe: Cache probe result.

    Returns:
        Healthy, degraded, or unhealthy aggregate status.
    """
    if database.status != "healthy":
        return "unhealthy"
    if cache_probe.status != "healthy":
        return "degraded"
    return "healthy"


async def _timed_probe(operation: Callable[[], Awaitable[None]]) -> DependencyProbeResult:
    """Run one dependency probe within the shared strict timeout.

    Args:
        operation: Read-only dependency operation.

    Returns:
        Probe status and elapsed duration.
    """
    started = time.perf_counter()
    try:
        async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
            await operation()
    except TimeoutError:
        probe_status: Literal["healthy", "unavailable", "timeout", "not_configured"] = (
            "timeout"
        )
    except ProbeTimeoutError as e:
        logger.warning("Operational dependency probe timed out: %s", e)
        probe_status = "timeout"
    except ProbeNotConfiguredError as e:
        logger.warning("Operational dependency probe not configured: %s", e)
        probe_status = "not_configured"
    except ProbeUnavailableError as e:
        logger.warning("Operational dependency probe unavailable: %s", e)
        probe_status = "unavailable"
    except ProbeError as e:
        logger.warning("Operational dependency probe failed: %s", e)
        probe_status = "unavailable"
    else:
        probe_status = "healthy"
    return DependencyProbeResult(
        status=probe_status,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )


async def database_probe(db: AsyncSession) -> None:
    """Execute the cheapest read-only database round trip.

    Args:
        db: Async database session.

    Raises:
        ProbeUnavailableError: If the database is unavailable.
    """
    try:
        await health_repository.execute_database_ping(db)
    except Exception as e:
        raise ProbeUnavailableError("Database ping failed", cause=e) from e


async def cache_probe() -> None:
    """Ping the initialized cache client without reading or mutating user data.

    Raises:
        ProbeNotConfiguredError: If the cache has not been initialized.
        ProbeUnavailableError: If the cache is unavailable.
    """
    if not cache.is_initialized:
        raise ProbeNotConfiguredError("Cache is not initialized")
    try:
        await cache.ping()
    except Exception as e:
        raise ProbeUnavailableError("Cache ping failed", cause=e) from e


async def get_dependency_health(db: AsyncSession) -> DependencyHealthResult:
    """Probe database and cache independently with strict time bounds.

    Args:
        db: Async database session.

    Returns:
        Structured per-dependency status and timings.
    """
    started = time.perf_counter()
    database_probe_result, cache_probe_result = await asyncio.gather(
        _timed_probe(lambda: database_probe(db)),
        _timed_probe(cache_probe),
    )
    overall = _overall_status(database_probe_result, cache_probe_result)
    total_duration_ms = round((time.perf_counter() - started) * 1000, 2)

    logger.info(
        "operational_health status=%s database_status=%s database_ms=%.2f "
        "cache_status=%s cache_ms=%.2f total_ms=%.2f",
        overall,
        database_probe_result.status,
        database_probe_result.duration_ms,
        cache_probe_result.status,
        cache_probe_result.duration_ms,
        total_duration_ms,
    )

    return DependencyHealthResult(
        status=overall,
        database=database_probe_result,
        cache=cache_probe_result,
        total_duration_ms=total_duration_ms,
    )


async def get_cache_quota_health() -> CacheQuotaHealthResult:
    """Report the observed monthly cache command budget snapshot.

    Purely in-process: reads the privacy-safe command counter from
    :func:`app.cache_quota.observe_cache_quota` without opening any connection or
    firing the alert sink. Monitoring polls this to see the near-limit /
    over-budget band and to confirm alerting and smoke-test throttling state.

    Returns:
        Aggregate budget snapshot with alert and throttle state.
    """
    from app.cache_quota import observe_cache_quota

    state = observe_cache_quota()
    return CacheQuotaHealthResult(
        status=state.status,
        observed_commands=state.used,
        budget=state.budget,
        remaining=state.remaining,
        usage_ratio=round(state.usage_ratio, 6),
        alerted=state.alerted,
        throttling=state.throttling,
        degraded=state.degraded,
    )


async def get_warmup_health(db: AsyncSession) -> DependencyHealthResult:
    """Exercise the real read-only database and cache dependency path.

    Args:
        db: Async database session.

    Returns:
        The same bounded dependency report used by production monitoring.
    """
    return await get_dependency_health(db)


async def get_warm_endpoint_result(
    request_state_startup_snapshot: object,
    db: AsyncSession,
) -> WarmEndpointResult:
    """Minimal warm endpoint for Vercel Fluid Compute instance reuse.

    This endpoint is designed to be lightweight - it does almost no CPU work
    and returns quickly. It includes instance diagnostics to measure
    Vercel instance reuse.

    The endpoint checks for recent activity and only returns a "warming"
    status when activity is detected. Otherwise, it returns "no_activity"
    to indicate the instance should be allowed to scale down.

    Guardrails:
    - Hard maximum daily request limit to prevent runaway workloads
    - Configurable inactivity threshold for stopping unnecessary pings

    Args:
        request_state_startup_snapshot: Startup snapshot from request state.
        db: Database session.

    Returns:
        WarmEndpointResult with instance diagnostics and activity status.
    """
    if not _is_warm_endpoint_enabled():
        return WarmEndpointResult(
            status="no_activity",
            instance=WarmInstanceDiagnostics(
                instance_id="",
                process_start_time_ns=0,
                request_count=0,
            ),
            has_active_session=False,
            request_count_today=0,
        )

    instance_id = _get_instance_id()
    snapshot = request_state_startup_snapshot
    request_count = getattr(snapshot, "invocation", 0)

    if not _is_heartbeat_within_limits(request_count):
        logger.warning(
            "Warm endpoint request limit exceeded: %d > %d",
            request_count,
            _get_heartbeat_max_requests(),
        )
        return WarmEndpointResult(
            status="no_activity",
            instance=WarmInstanceDiagnostics(
                instance_id=instance_id,
                process_start_time_ns=getattr(snapshot, "process_started_at_ns", 0),
                request_count=request_count,
            ),
            has_active_session=False,
            request_count_today=request_count,
        )

    has_activity = await health_repository.check_recent_activity(
        db, _get_inactivity_threshold_seconds()
    )

    return WarmEndpointResult(
        status="warming" if has_activity else "no_activity",
        instance=WarmInstanceDiagnostics(
            instance_id=instance_id,
            process_start_time_ns=getattr(snapshot, "process_started_at_ns", 0),
            request_count=request_count,
            startup_time_ms=getattr(snapshot, "startup_duration_ms", None),
            process_age_ms=getattr(snapshot, "process_age_ms", None),
        ),
        has_active_session=has_activity,
        request_count_today=request_count,
    )