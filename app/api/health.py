"""Bounded warm-up endpoint for Vercel Fluid Compute instance reuse."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import health_probe
from app.startup_diagnostics import StartupSnapshot

router = APIRouter(tags=["health"])


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
            process_to_startup_ms=None,
            startup_cpu_ms=None,
            startup_complete=False,
            startup_duration_ms=0.0,
            application_import_ms=0.0,
            application_creation_ms=0.0,
            lifespan_ms=0.0,
            heavy_initialized=False,
            heavy_init_duration_ms=None,
            heavy_init_process_age_ms=None,
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
