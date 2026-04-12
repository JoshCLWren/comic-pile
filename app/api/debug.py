"""Debug logging endpoint for client-side terminal output."""

import sys

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter()

ALLOWED_LEVELS = {"INFO", "WARN", "ERROR"}
MAX_MESSAGE_LENGTH = 2000


@router.post("/debug/log")
async def log_message(request: Request) -> dict[str, str]:
    """Receive client-side log messages and output to server terminal."""
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid log payload",
        )

    level = str(body.get("level", "info")).upper()
    if level not in ALLOWED_LEVELS:
        level = "INFO"

    message = str(body.get("message", ""))[:MAX_MESSAGE_LENGTH]
    data = body.get("data")

    log_prefix = f"[CLIENT {level}]"

    if data:
        print(f"{log_prefix} {message} | Data: {data}", file=sys.stderr, flush=True)
    else:
        print(f"{log_prefix} {message}", file=sys.stderr, flush=True)

    return {"status": "logged"}
