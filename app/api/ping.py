"""Lightweight ping endpoint for Vercel cold-start mitigation."""

from fastapi import APIRouter

router = APIRouter(tags=["ping"])


@router.get("/ping", include_in_schema=False)
async def ping() -> dict[str, str]:
    """Lightweight ping endpoint with zero database/ORM dependencies.

    Returns:
        Simple alive status response.
    """
    return {"status": "alive"}