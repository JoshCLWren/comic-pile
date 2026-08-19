"""Lightweight ping endpoint for cold-start mitigation."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Return a minimal alive response.

    This endpoint has zero database, ORM, or heavy dependency
    initialization overhead. It exists solely to keep the Vercel
    Python serverless function warm and avoid cold starts.

    Returns:
        Simple status dict with no external dependencies.
    """
    return {"status": "alive"}
