"""Lightweight ping endpoint for cold-start mitigation."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/ping", tags=["ping"])
async def ping() -> dict[str, str]:
    """Return alive status with zero database dependencies."""
    return {"status": "alive"}
