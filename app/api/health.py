"""Bounded operational health and warm-up endpoints."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])
DEPENDENCY_TIMEOUT_SECONDS = 2.0


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
    client = getattr(cache, "_client", None)
    if not cache.is_initialized or client is None:
        raise RuntimeError("Cache is not initialized")
    await client.ping()


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


@router.get("/v1/health/live")
async def liveness() -> dict[str, str]:
    """Confirm that the FastAPI process can serve requests without dependencies.

    Returns:
        Stable liveness response.
    """
    return {"status": "alive"}


@router.get("/v1/health/dependencies", response_model=DependencyHealthResponse)
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
        return JSONResponse(status_code=status.HTTP_207_MULTI_STATUS, content=payload.model_dump())
    return payload


@router.get("/v1/health/warmup", response_model=DependencyHealthResponse)
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
async def legacy_health(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str] | JSONResponse:
    """Preserve the legacy database-only health contract without operational details.

    Args:
        db: Async database session.

    Returns:
        Stable database connectivity status without timings or cache metadata.
    """
    database_probe = await _timed_probe(lambda: _database_probe(db))
    if database_probe.status == "healthy":
        return {"status": "healthy", "database": "connected"}
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "unhealthy", "database": "disconnected"},
    )
