"""Password reset service owning forgot-password and reset-completion logic."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status

from app.auth import hash_password
from app.repositories.password_reset_token_repository import (
    create_token,
    delete_all_for_user,
    get_token_by_digest,
    mark_used,
)
from app.repositories.reading_session_repository import delete_all_reading_sessions_for_user
from app.repositories.user_repository import get_user_by_email, get_user_by_id
from app.services.password_reset_mailer import (
    FakePasswordResetMailer,
    PasswordResetDeliveryError,
    get_password_reset_mailer,
)
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTasks

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_MINUTES = 30


class PasswordResetDeliveryHandoff:
    """Provider-neutral delivery interface for #2778."""

    def __init__(
        self,
        recipient_email: str,
        user_username: str,
        reset_token: str,
        expires_at: datetime,
    ) -> None:
        """Initialize the handoff with delivery metadata."""
        self.recipient_email = recipient_email
        self.user_username = user_username
        self.reset_token = reset_token
        self.expires_at = expires_at


async def request_forgot_password(
    db: AsyncSession,
    email: str,
) -> PasswordResetDeliveryHandoff | None:
    """Generate a reset token for the email if an account exists.

    Same externally visible acknowledgement regardless of existence.
    Only returns handoff when user exists (for mail provider #2778).
    """
    user = await get_user_by_email(db, email)
    if user is None or not user.email:
        return None
    # Extract attributes before commit to avoid session expiration
    recipient_email = user.email
    user_username = user.username
    # Supersede older tokens for this user
    await delete_all_for_user(db, user.id)
    raw_token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(minutes=TOKEN_EXPIRY_MINUTES)
    await create_token(db, user_id=user.id, token_digest=digest, expires_at=expires_at)
    await db.commit()
    return PasswordResetDeliveryHandoff(
        recipient_email=recipient_email,
        user_username=user_username,
        reset_token=raw_token,
        expires_at=expires_at,
    )


async def deliver_password_reset_email(handoff: PasswordResetDeliveryHandoff) -> None:
    """Deliver one reset message off the request/response path.

    Runs as a background task after the acknowledgement is returned so that
    provider latency (up to the adapter timeout during an outage) never
    becomes a caller-observable timing signal that separates a known email
    address from an unknown one. The token row is already committed by the
    time this runs, so a failure never corrupts token state, and the outcome
    is logged operationally (status only, no token, no leak to the caller).

    Args:
        handoff: Provider-neutral delivery data from the token handoff.
    """
    mailer = get_password_reset_mailer()
    if isinstance(mailer, FakePasswordResetMailer):
        logger.warning(
            "Password reset email is being recorded in-memory instead of "
            "sent: outbound email is not configured.",
            extra={"event": "password_reset_email_unconfigured"},
        )
    try:
        await mailer.send_password_reset(
            recipient_email=handoff.recipient_email,
            username=handoff.user_username,
            reset_token=handoff.reset_token,
            expires_at=handoff.expires_at,
        )
    except PasswordResetDeliveryError as exc:
        logger.warning(
            "Password reset email delivery failed: %s",
            exc,
            extra={"event": "password_reset_delivery_failed"},
        )
    except Exception:
        logger.warning(
            "Password reset email delivery failed unexpectedly.",
            extra={"event": "password_reset_delivery_failed"},
        )


async def handle_forgot_password_request(
    db: AsyncSession,
    email: str,
    background_tasks: BackgroundTasks,
) -> None:
    """Run the full enumeration-safe forgot-password flow including delivery.

    This is the router's single service entry point (house layering rule): it
    generates the reset token via :func:`request_forgot_password` and then
    schedules delivery through the provider-neutral mailer boundary on the
    request's background task. The raw token is passed only to the mailer so
    it can construct the link; it is never persisted or logged here.

    Delivery is deliberately deferred: returning the acknowledgement before
    the outbound attempt keeps known and unknown addresses indistinguishable
    in response time even when the provider is slow or down, and a mail
    outage neither leaks account existence nor corrupts token state (the
    token row is committed before this function returns).

    Args:
        db: Async database session.
        email: Recovery email from the request body.
        background_tasks: Request-scoped background task queue.
    """
    handoff = await request_forgot_password(db, email)
    if handoff is None:
        # Unknown email: identical observable behavior, no delivery attempt.
        return
    background_tasks.add_task(deliver_password_reset_email, handoff)


async def complete_reset(
    db: AsyncSession,
    token_string: str,
    new_password: str,
) -> bool:
    """Validate token, atomically update password, consume token, revoke sessions.

    Returns True on success. Raises HTTPException on failure with safe messages.
    """
    digest = hashlib.sha256(token_string.encode()).hexdigest()
    token_obj = await get_token_by_digest(db, digest)
    if token_obj is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset request.",
        )
    # Pre-load needed values before any commit
    user_id = token_obj.user_id
    token_id = token_obj.id
    now = datetime.now(UTC)
    if token_obj.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset request.",
        )
    if token_obj.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset request.",
        )
    # Load user to extract before commit
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset request.",
        )
    # Atomically update password hash
    user.password_hash = hash_password(new_password)
    user.password_changed_at = now
    # Consume token
    await mark_used(db, token_id)
    await delete_all_reading_sessions_for_user(db, user_id)
    # Reading history is deliberately preserved across a password reset. Password
    # changes revoke prior credentials through `password_changed_at` (checked by
    # `get_current_user`) and `revoked_token`, so authentication state never has to
    # touch the reading-session tables. See docs/PASSWORD_RESET_INCIDENT_AUDIT_2026-09-30.md.
    await db.commit()
    return True
