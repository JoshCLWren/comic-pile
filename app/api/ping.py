"""Lightweight ping endpoint for Vercel cold-start mitigation.

This module exports a minimal FastAPI Router with a single GET /ping endpoint
that returns immediately without any database queries, ORM handshakes, or
heavy dependency initialization. It boots instantly because it imports nothing
beyond FastAPI core types.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["ping"])


@router.get("/ping", include_in_schema=False)
async def ping() -> JSONResponse:
    """Minimal liveness probe for Vercel container warmkeeping.

    Returns instantly without touching the database or any ORM. Designed
    for high-frequency polling from the frontend to keep the serverless
    container from spinning down.

    Returns:
        JSONResponse with {"status": "alive"}.
    """
    return JSONResponse(content={"status": "alive"})