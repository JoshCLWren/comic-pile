"""Bounded operational health and warm-up endpoints."""

from __future__ import annotations

import dataclasses
import logging
import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import health_probe
from app.startup_diagnostics import StartupSnapshot

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


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


@router.get("/health/live", include_in_schema=False)
async def liveness() -> dict[str, str]:
    """Confirm that the FastAPI process can serve requests without dependencies.

    Returns:
        Stable liveness response.
    """
    return {"status": "alive"}


@router.get(
    "/health/dependencies",
    response_model=health_probe.DependencyHealthResult,
    include_in_schema=False,
)
async def dependency_health(
    _: Annotated[None, Depends(_authorize_operational_probe)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> health_probe.DependencyHealthResult | JSONResponse:
    """Probe database and cache independently with strict time bounds.

    Args:
        _: Operational-probe authorization result.
        db: Async database session.

    Returns:
        Structured per-dependency status and timings.
    """
    result = await health_probe.get_dependency_health(db)

    if result.status == "unhealthy":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=dataclasses.asdict(result),
        )
    if result.status == "degraded":
        return JSONResponse(
            status_code=status.HTTP_207_MULTI_STATUS,
            content=dataclasses.asdict(result),
        )
    return result


@router.get(
    "/health/cache-quota",
    response_model=health_probe.CacheQuotaHealthResult,
    include_in_schema=False,
)
async def cache_quota_health(
    _: Annotated[None, Depends(_authorize_operational_probe)],
) -> health_probe.CacheQuotaHealthResult:
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
    return await health_probe.get_cache_quota_health()


@router.get(
    "/health/warmup",
    response_model=health_probe.DependencyHealthResult,
    include_in_schema=False,
)
async def warmup(
    _: Annotated[None, Depends(_authorize_operational_probe)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> health_probe.DependencyHealthResult | JSONResponse:
    """Exercise the real read-only database and cache dependency path.

    Args:
        _: Operational-probe authorization result.
        db: Async database session.

    Returns:
        The same bounded dependency report used by production monitoring.
    """
    result = await health_probe.get_warmup_health(db)

    if result.status == "unhealthy":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=dataclasses.asdict(result),
        )
    if result.status == "degraded":
        return JSONResponse(
            status_code=status.HTTP_207_MULTI_STATUS,
            content=dataclasses.asdict(result),
        )
    return result


@router.get("/health", include_in_schema=False)
async def legacy_health() -> dict[str, str]:
    """Preserve the public legacy health URL as dependency-free liveness.

    Database and cache checks live only on the explicit bounded operational
    endpoints so an uptime probe cannot wake Neon or wait on Redis.

    Returns:
        Stable liveness response.
    """
    return {"status": "alive"}


async def warm_endpoint(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> health_probe.WarmEndpointResult:
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
        WarmEndpointResult with instance diagnostics and activity status.
    """
    snapshot = getattr(request.state, "startup_snapshot", None)
    if snapshot is None:
        snapshot = StartupSnapshot(
            invocation=0,
            cold=True,
            process_age_ms=0.0,
            startup_complete=False,
            startup_duration_ms=0.0,
            application_import_ms=0.0,
            application_creation_ms=0.0,
            lifespan_ms=0.0,
            heavy_initialized=False,
            heavy_init_duration_ms=None,
            deployment_id="unknown",
            process_started_at_ns=0,
        )

    return await health_probe.get_warm_endpoint_result(snapshot, db)


if health_probe._is_warm_endpoint_enabled():
    router.add_api_route(
        "/instance/warm",
        warm_endpoint,
        response_model=health_probe.WarmEndpointResult,
        include_in_schema=False,
    )