"""Debug logging endpoint for client-side terminal output."""

import sys

from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/debug/log")
async def log_message(request: Request) -> dict[str, str]:
    """Receive client-side log messages and output to server terminal."""
    body = await request.json()
    level = body.get("level", "info").upper()
    message = body.get("message", "")
    data = body.get("data")

    log_prefix = f"[CLIENT {level}]"

    if data:
        print(f"{log_prefix} {message} | Data: {data}", file=sys.stderr, flush=True)
    else:
        print(f"{log_prefix} {message}", file=sys.stderr, flush=True)

    return {"status": "logged"}
