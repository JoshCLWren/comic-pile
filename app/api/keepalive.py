"""Lightweight keep-alive endpoint for Neon warm-pool maintenance.

This endpoint runs a minimal ``SELECT 1`` on the pooled database connection
to prevent Neon from suspending the compute instance during active use.
It requires no authentication and is designed to be called periodically
from the frontend while the tab is visible and the user is active.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter()


@router.get("/keepalive")
async def keepalive(
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Execute a minimal database round-trip to keep the Neon pool warm.

    This endpoint:
    - Runs a single ``SELECT 1`` on the pooled asyncpg connection
    - Requires no authentication
    - Returns a simple status response
    - Triggers heavy initialization (database pool setup) on first call

    The frontend calls this periodically while the tab is visible and
    the user is active, stopping when the tab is hidden or the user
    becomes idle. This keeps the Neon compute warm only during actual
    usage, avoiding the ~408ms cold-wake penalty on the first action.

    Returns:
        Simple status dict confirming the database round-trip succeeded.
    """
    await db.execute(text("SELECT 1"))
    return {"status": "warmed"}