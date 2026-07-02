"""FastAPI dependencies for authentication and access control."""

from fastapi import HTTPException

from app.config import get_app_settings


def require_debug_routes() -> None:
    """Dependency that raises 404 if debug routes are disabled."""
    app_settings = get_app_settings()
    if not app_settings.enable_debug_routes:
        raise HTTPException(status_code=404, detail="Not Found")


def require_internal_ops_routes() -> None:
    """Dependency that raises 404 if internal ops routes are disabled."""
    app_settings = get_app_settings()
    if not app_settings.enable_internal_ops_routes:
        raise HTTPException(status_code=404, detail="Not Found")
