"""Debug logging endpoint for client-side terminal output."""

import sys

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_app_settings
from app.database import get_db
from app.middleware import limiter
from app.models.user import User

router = APIRouter()

ALLOWED_LEVELS = {"INFO", "WARN", "ERROR"}
MAX_MESSAGE_LENGTH = 2000

app_settings = get_app_settings()


def check_debug_routes_enabled() -> None:
    """Check if debug routes are enabled via environment variable."""
    if app_settings.environment == "production":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )


@router.post("/debug/log")
@limiter.limit("10/minute")
async def log_message(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Receive client-side log messages and output to server terminal."""
    # Check if debug routes are enabled (defense in depth)
    check_debug_routes_enabled()

    # Check if user is admin
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

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
