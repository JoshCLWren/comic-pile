"""Lightweight ping endpoint for cold-start mitigation."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Return a minimal alive response.

    This endpoint has zero database, ORM, or heavy dependency
    initialization overhead. Lifespan startup is intentionally lightweight
    and heavy initialization (database connectivity, durable cache
    accounting, cache provider) is deferred until the first non-ping
    request. A cold ``GET /api/ping`` therefore never opens a
    PostgreSQL connection or reserves a cache block.

    Returns:
        Simple status dict with no external dependencies.
    """
    return {"status": "alive"}
