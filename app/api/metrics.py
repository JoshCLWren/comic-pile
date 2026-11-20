"""Endpoint exposing simple performance metrics."""
from fastapi import APIRouter

from app.middleware.performance import (
    get_startup_duration,
    get_startup_time,
)

router = APIRouter()

@router.get("/metrics", description="Return simple performance metrics.")
async def metrics() -> dict[str, float | None]:
    """Return metrics about application startup.

    Returns:
        Dict with keys:
        - startup_time: epoch seconds when the app started.
        - startup_duration: seconds taken to start up.
    """
    return {
        "startup_time": get_startup_time(),
        "startup_duration": get_startup_duration(),
    }
