"""Password reset token query construction and persistence."""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.password_reset_token import PasswordResetToken


async def create_token(
    db: AsyncSession,
    *,
    user_id: int,
    token_digest: str,
    expires_at: datetime,
) -> PasswordResetToken:
    """Create a password reset token for a user."""
    token = PasswordResetToken(
        user_id=user_id,
        token_digest=token_digest,
        expires_at=expires_at,
    )
    db.add(token)
    return token


async def get_token_by_digest(db: AsyncSession, digest: str) -> PasswordResetToken | None:
    """Look up a password reset token by its digest."""
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_digest == digest).limit(1)
    )
    return result.scalar_one_or_none()


async def delete_all_for_user(db: AsyncSession, user_id: int) -> None:
    """Delete all password reset tokens for a user."""
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))


async def mark_used(db: AsyncSession, token_id: int) -> None:
    """Mark a reset token as used by setting its used_at timestamp."""
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.id == token_id).limit(1)
    )
    token = result.scalar_one_or_none()
    if token is not None:
        token.used_at = datetime.now(UTC)
