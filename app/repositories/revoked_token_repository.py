"""Revoked-token query construction and persistence.

All SQLAlchemy access for the ``RevokedToken`` model family lives here.
Functions return ORM models or plain values; callers (services) own
transactions.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.revoked_token import RevokedToken
from app.models.user import User


async def is_token_revoked(db: AsyncSession, jti: str) -> bool:
    """Check whether a token JTI has been revoked.

    Args:
        db: Database session.
        jti: JWT token identifier to check.

    Returns:
        ``True`` when the JTI is present in the revoked-tokens table.
    """
    result = await db.execute(select(RevokedToken).where(RevokedToken.jti == jti).limit(1))
    return result.scalar_one_or_none() is not None


async def get_user_by_username_with_revocation_check(
    db: AsyncSession,
    username: str,
    jti: str,
) -> tuple[User, bool]:
    """Look up a user and check revocation status in a single round trip.

    Args:
        db: Database session.
        username: Username to look up.
        jti: JWT token identifier to check for revocation.

    Returns:
        Tuple of ``(user, is_revoked)``.
    """
    result = await db.execute(
        select(User, RevokedToken.id)
        .outerjoin(RevokedToken, RevokedToken.jti == jti)
        .where(User.username == username)
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        raise ValueError("User not found")
    user = row[0]
    is_revoked = row[1] is not None
    _ = user.id  # Preload ID in async context to avoid MissingGreenlet
    return user, is_revoked


async def add_revoked_token(
    db: AsyncSession,
    *,
    user_id: int,
    jti: str,
    expires_at: datetime,
) -> None:
    """Persist a revoked-token record.

    Args:
        db: Database session.
        user_id: Owner of the revoked token.
        jti: JWT token identifier.
        expires_at: Original expiration timestamp of the token.

    Note:
        Duplicate JTIs are silently ignored (idempotent revoke).
    """
    revoked_token = RevokedToken(
        user_id=user_id,
        jti=jti,
        expires_at=expires_at,
    )
    db.add(revoked_token)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
