"""Route-level access control gates for debug, internal-ops, and cron endpoints."""

import logging
import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.config import get_app_settings

logger = logging.getLogger(__name__)


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


def require_cron_secret(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Require Vercel Cron's bearer secret on machine-triggered endpoints.

    Vercel sends ``Authorization: Bearer <CRON_SECRET>`` when the project has a
    ``CRON_SECRET`` environment variable configured. This gate fails closed: a
    deployment without a usable secret refuses to run the handler, and a
    missing or mismatched header is rejected before any service work starts.

    The presented value and the configured secret are never logged.

    Args:
        authorization: Raw ``Authorization`` request header.

    Raises:
        HTTPException: 503 when the deployment secret is not configured, or 401
            when the presented bearer secret is missing or incorrect.
    """
    expected = get_app_settings().usable_cron_secret
    if expected is None:
        logger.error("cron_endpoint_secret_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cron endpoint is not configured",
        )

    scheme, separator, presented = (authorization or "").partition(" ")
    # Compare bytes so an arbitrary non-ASCII header can never raise from
    # ``compare_digest`` and turn an authentication rejection into a 500.
    if (
        not separator
        or scheme.lower() != "bearer"
        or not presented
        or not secrets.compare_digest(
            presented.encode("utf-8"), expected.encode("utf-8")
        )
    ):
        logger.warning("cron_endpoint_secret_rejected")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
