"""FastAPI dependencies for authentication and access control."""

import os

from fastapi import HTTPException


def require_debug_routes() -> None:
    """Dependency that raises 404 if debug routes are disabled."""
    if not os.getenv("ENABLE_DEBUG_ROUTES", "false").lower() == "true":
        raise HTTPException(status_code=404, detail="Not Found")


def require_internal_ops_routes() -> None:
    """Dependency that raises 404 if internal ops routes are disabled."""
    if not os.getenv("ENABLE_INTERNAL_OPS_ROUTES", "false").lower() == "true":
        raise HTTPException(status_code=404, detail="Not Found")
