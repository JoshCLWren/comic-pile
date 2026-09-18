"""Login security: failed-attempt tracking and account lockout."""

import logging

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.failed_login_repository import (
    clear_attempts_for_username,
    count_recent_attempts,
    record_failed_attempt,
)

logger = logging.getLogger(__name__)

MAX_USERNAME_FAILURES = 5
USERNAME_LOCKOUT_MINUTES = 15
MAX_IP_FAILURES = 10
IP_LOCKOUT_MINUTES = 30

LOCKOUT_ERROR_MESSAGE = "Incorrect username or password"


def get_client_ip(request_headers: dict, client_host: str | None) -> str:
    """Extract client IP from request, respecting X-Forwarded-For.

    Args:
        request_headers: Dict-like request headers.
        client_host: The direct client host from ``request.client.host``.

    Returns:
        Client IP address string.
    """
    forwarded = request_headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return client_host or "unknown"


async def check_login_lockout(db: AsyncSession, username: str, ip_address: str) -> None:
    """Raise HTTP 401 if the username or IP is locked out.

    Args:
        db: SQLAlchemy async session.
        username: Login username to check.
        ip_address: Client IP address to check.

    Raises:
        HTTPException: 401 with generic message when locked out.
    """
    username_failures = await count_recent_attempts(
        db, username=username, window_minutes=USERNAME_LOCKOUT_MINUTES
    )
    if username_failures >= MAX_USERNAME_FAILURES:
        logger.warning(
            "Login locked out for username '%s' (%d failures in %d min)",
            username,
            username_failures,
            USERNAME_LOCKOUT_MINUTES,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=LOCKOUT_ERROR_MESSAGE,
        )

    ip_failures = await count_recent_attempts(
        db, ip_address=ip_address, window_minutes=IP_LOCKOUT_MINUTES
    )
    if ip_failures >= MAX_IP_FAILURES:
        logger.warning(
            "Login locked out for IP '%s' (%d failures in %d min)",
            ip_address,
            ip_failures,
            IP_LOCKOUT_MINUTES,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=LOCKOUT_ERROR_MESSAGE,
        )


async def record_failed_login(db: AsyncSession, username: str, ip_address: str) -> None:
    """Persist a failed-login attempt record.

    Args:
        db: SQLAlchemy async session.
        username: The attempted username.
        ip_address: The client IP address.
    """
    await record_failed_attempt(db, username=username, ip_address=ip_address)


async def clear_failed_logins(db: AsyncSession, username: str) -> None:
    """Remove all failed-login records for a username after successful login.

    Args:
        db: SQLAlchemy async session.
        username: The username whose attempts to clear.
    """
    await clear_attempts_for_username(db, username)
