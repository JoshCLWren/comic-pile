"""Compatibility endpoint retained for older clients without waking Neon.

Database liveness and readiness are checked explicitly through
`/api/v1/health/dependencies`, not via synthetic frontend pings.
"""

from fastapi import APIRouter

from app.schemas import KeepaliveResponse

router = APIRouter()


@router.get("/keepalive", response_model=KeepaliveResponse, include_in_schema=False)
async def keepalive() -> KeepaliveResponse:
    """Respond to obsolete keepalive calls without opening a DB connection."""
    return KeepaliveResponse(status="disabled")
