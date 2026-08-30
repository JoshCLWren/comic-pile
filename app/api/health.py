"""Bounded operational health and warm-up endpoints."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache
from app.cache_quota import observe_cache_quota
from app.database import get_db
from app.models import Event

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])
DEPENDENCY_TIMEOUT_SECONDS = 2.0


def _get_heartbeat_max_requests() -> int:
    """Get the maximum requests allowed per day for the warm endpoint."""
    raw_value = os.getenv("WARM_ENDPOINT_MAX_DAILY_REQUESTS", "1000")
    try:
        return max(1, min(10000, int(raw_value)))
    except ValueError:
        return 1000


def _get_inactivity_threshold_seconds() -> int:
    """Get the inactivity threshold in seconds for stopping heartbeats."""
    raw_value = os.getenv("WARM_ENDPOINT_INACTIVITY_SECONDS", "1800")
    try:
        return max(60, min(86400, int(raw_value)))
    except ValueError:
        return 1800


def _is_warm_endpoint_enabled() -> bool:
    """Check if the warm endpoint is enabled."""
    return os.getenv("WARM_ENDPOINT_ENABLED", "false").lower() == "true"


def _is_heartbeat_within_limits(request_count: int) -> bool:
    """Check if the heartbeat is within the daily request limit."""
    return request_count <= _get_heartbeat_max_requests()


class DependencyProbe(BaseModel):
    """One bounded dependency probe result."""

    status: Literal["healthy", "unavailable", "timeout", "not_configured"]
    duration_ms: float


class DependencyHealthResponse(BaseModel):
    """Operational dependency-health response without sensitive metadata."""

    status: Literal["healthy", "degraded", "unhealthy"]
    database: DependencyProbe
    cache: DependencyProbe
    total_duration_ms: float


class CacheQuotaHealthResponse(BaseModel):
    """Visible cache-quota snapshot for budget alerting.

    Surfaces the privacy-safe monthly command budget state so operators and
    automated monitoring can detect "approaching the budget" before the hard
    limit is reached. Contains only aggregate counts and ratios; never cache
    keys, user data, or provider credentials.
    """

    status: Literal["ok", "near-limit", "over-budget"]
    observed_commands: int
    budget: int
    remaining: int
    usage_ratio: float
    alerted: bool
    throttling: bool


class WarmInstanceDiagnostics(BaseModel):
    """Instance-level diagnostics for Vercel warm endpoint."""

    instance_id: str
    process_start_time_ns: int
    request_count: int
    startup_time_ms: float | None = None
    process_age_ms: float | None = None


class WarmResponse(BaseModel):
    """Response from the warm endpoint for instance reuse tracking."""

    status: Literal["warming", "cold", "no_activity"]
    instance: WarmInstanceDiagnostics
    has_active_session: bool
    request_count_today: int


async def _authorize_operational_probe(
    x_health_token: Annotated[str | None, Header()] = None,
) -> None:
    """Require the configured health token for detailed operational probes.

    Args:
        x_health_token: Token supplied by trusted production monitoring.

    Raises:
        HTTPException: If a configured token is missing or incorrect.
    """
    expected = os.getenv("HEALTH_CHECK_TOKEN")
    if expected and (
        x_health_token is None or not secrets.compare_digest(x_health_token, expected)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


async def _timed_probe(operation: Callable[[], Awaitable[None]]) -> DependencyProbe:
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
    except Exception:
        logger.warning("Operational dependency probe failed", exc_info=True)
        probe_status = "unavailable"
    else:
        probe_status = "healthy"
    return DependencyProbe(
        status=probe_status,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )


async def _database_probe(db: AsyncSession) -> None:
    """Execute the cheapest read-only database round trip.

    Args:
        db: Async database session.
    """
    await db.execute(text("SELECT 1"))


async def _cache_probe() -> None:
    """Ping the initialized cache client without reading or mutating user data.

    Raises:
        RuntimeError: If the cache has not been initialized.
    """
    await cache.ping()


def _overall_status(
    database: DependencyProbe,
    cache_probe: DependencyProbe,
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


@router.get("/health/live", include_in_schema=False)
async def liveness() -> dict[str, str]:
    """Confirm that the FastAPI process can serve requests without dependencies.

    Returns:
        Stable liveness response.
    """
    return {"status": "alive"}


@router.get(
    "/health/dependencies",
    response_model=DependencyHealthResponse,
    include_in_schema=False,
)
async def dependency_health(
    _: Annotated[None, Depends(_authorize_operational_probe)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DependencyHealthResponse | JSONResponse:
    """Probe database and cache independently with strict time bounds.

    Args:
        _: Operational-probe authorization result.
        db: Async database session.

    Returns:
        Structured per-dependency status and timings.
    """
    started = time.perf_counter()
    database_probe, cache_probe = await asyncio.gather(
        _timed_probe(lambda: _database_probe(db)),
        _timed_probe(_cache_probe),
    )
    overall = _overall_status(database_probe, cache_probe)
    payload = DependencyHealthResponse(
        status=overall,
        database=database_probe,
        cache=cache_probe,
        total_duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    logger.info(
        "operational_health status=%s database_status=%s database_ms=%.2f "
        "cache_status=%s cache_ms=%.2f total_ms=%.2f",
        payload.status,
        payload.database.status,
        payload.database.duration_ms,
        payload.cache.status,
        payload.cache.duration_ms,
        payload.total_duration_ms,
    )
    if overall == "unhealthy":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(),
        )
    if overall == "degraded":
        return JSONResponse(
            status_code=status.HTTP_207_MULTI_STATUS,
            content=payload.model_dump(),
        )
    return payload


@router.get(
    "/health/cache-quota",
    response_model=CacheQuotaHealthResponse,
    include_in_schema=False,
)
async def cache_quota_health(
    _: Annotated[None, Depends(_authorize_operational_probe)],
) -> CacheQuotaHealthResponse:
    """Report the observed monthly cache command budget snapshot.

    Purely in-process: reads the privacy-safe command counter from
    :func:`app.cache_quota.observe_cache_quota` without opening any connection or
    firing the alert sink. Monitoring polls this to see the near-limit /
    over-budget band and to confirm alerting and smoke-test throttling state.

    Args:
        _: Operational-probe authorization result.

    Returns:
        Aggregate budget snapshot with alert and throttle state.
    """
    state = observe_cache_quota()
    return CacheQuotaHealthResponse(
        status=state.status,
        observed_commands=state.used,
        budget=state.budget,
        remaining=state.remaining,
        usage_ratio=round(state.usage_ratio, 6),
        alerted=state.alerted,
        throttling=state.throttling,
    )


@router.get(
    "/health/warmup",
    response_model=DependencyHealthResponse,
    include_in_schema=False,
)
async def warmup(
    _: Annotated[None, Depends(_authorize_operational_probe)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DependencyHealthResponse | JSONResponse:
    """Exercise the real read-only database and cache dependency path.

    Args:
        _: Operational-probe authorization result.
        db: Async database session.

    Returns:
        The same bounded dependency report used by production monitoring.
    """
    return await dependency_health(None, db)


@router.get("/health", include_in_schema=False)
async def legacy_health() -> dict[str, str]:
    """Preserve the public legacy health URL as dependency-free liveness.

    Database and cache checks live only on the explicit bounded operational
    endpoints so an uptime probe cannot wake Neon or wait on Redis.

    Returns:
        Stable liveness response.
    """
    return {"status": "alive"}


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


async def _check_recent_activity(db: AsyncSession) -> bool:
    """Check if there's recent session activity within the inactivity threshold.

    Args:
        db: Database session.

    Returns:
        True if recent activity exists, False otherwise.
    """
    threshold_seconds = _get_inactivity_threshold_seconds()
    cutoff_time = datetime.now(UTC) - timedelta(seconds=threshold_seconds)

    result = await db.execute(
        select(func.max(Event.timestamp)).where(Event.timestamp >= cutoff_time)
    )
    last_event_time = result.scalar_one_or_none()
    if inspect.isawaitable(last_event_time):
        last_event_time = await last_event_time
    return last_event_time is not None


async def warm_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WarmResponse:
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

    Returns:
        WarmResponse with instance diagnostics and activity status.
    """
    if not _is_warm_endpoint_enabled():
        return WarmResponse(
            status="no_activity",
            instance=WarmInstanceDiagnostics(
                instance_id=_get_instance_id(),
                process_start_time_ns=0,
                request_count=0,
            ),
            has_active_session=False,
            request_count_today=0,
        )

    instance_id = _get_instance_id()
    snapshot = request.state.startup_snapshot
    request_count = snapshot.invocation

    if not _is_heartbeat_within_limits(request_count):
        logger.warning(
            "Warm endpoint request limit exceeded: %d > %d",
            request_count,
            _get_heartbeat_max_requests(),
        )
        return WarmResponse(
            status="no_activity",
            instance=WarmInstanceDiagnostics(
                instance_id=instance_id,
                process_start_time_ns=snapshot.process_started_at_ns,
                request_count=request_count,
            ),
            has_active_session=False,
            request_count_today=request_count,
        )

    has_activity = await _check_recent_activity(db)

    return WarmResponse(
        status="warming" if has_activity else "no_activity",
        instance=WarmInstanceDiagnostics(
            instance_id=instance_id,
            process_start_time_ns=snapshot.process_started_at_ns,
            request_count=request_count,
            startup_time_ms=snapshot.startup_duration_ms,
            process_age_ms=snapshot.process_age_ms,
        ),
        has_active_session=has_activity,
        request_count_today=request_count,
    )


if _is_warm_endpoint_enabled():
    router.add_api_route(
        "/instance/warm",
        warm_endpoint,
        response_model=WarmResponse,
        include_in_schema=False,
    )
