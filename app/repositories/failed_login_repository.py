"""Failed-login-attempt query construction and persistence.

All SQLAlchemy access for the ``FailedLoginAttempt`` model family lives
here. Functions return plain values; callers (services) own transactions.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.failed_login_attempt import FailedLoginAttempt


async def count_recent_attempts(
    db: AsyncSession,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    window_minutes: int = 15,
) -> int:
    """Count failed login attempts within a time window.

    Args:
        db: SQLAlchemy async session.
        username: Filter by username (optional).
        ip_address: Filter by IP address (optional).
        window_minutes: Look-back window in minutes.

    Returns:
        Number of matching attempts.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
    conditions = [FailedLoginAttempt.attempted_at >= cutoff]
    if username is not None:
        conditions.append(FailedLoginAttempt.username == username)
    if ip_address is not None:
        conditions.append(FailedLoginAttempt.ip_address == ip_address)

    result = await db.execute(
        select(func.count()).select_from(FailedLoginAttempt).where(*conditions)
    )
    return result.scalar_one()


async def record_failed_attempt(
    db: AsyncSession,
    *,
    username: str,
    ip_address: str,
) -> None:
    """Persist a failed-login attempt record.

    Args:
        db: SQLAlchemy async session.
        username: The attempted username.
        ip_address: The client IP address.
    """
    attempt = FailedLoginAttempt(
        username=username,
        ip_address=ip_address,
    )
    db.add(attempt)
    await db.commit()


async def clear_attempts_for_username(db: AsyncSession, username: str) -> None:
    """Remove all failed-login records for a username after successful login.

    Args:
        db: SQLAlchemy async session.
        username: The username whose attempts to clear.
    """
    await db.execute(delete(FailedLoginAttempt).where(FailedLoginAttempt.username == username))
    await db.commit()
