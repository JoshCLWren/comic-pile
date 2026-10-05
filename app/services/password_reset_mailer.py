"""Password-reset outbound email delivery behind a provider-neutral boundary.

Issue #2778 delivers password-reset links through Gmail SMTP without coupling the
reset domain/security model (owned by #2777) to a vendor. The reset domain
depends only on :class:`PasswordResetDeliveryHandoff
<app.services.password_reset_service.PasswordResetDeliveryHandoff>`; this
module owns everything at and beyond the delivery boundary:

- constructing the user-facing reset URL from the one-time raw token,
- composing the minimal reset message with expiry/security language,
- sending through the configured provider,
- surfacing provider failures operationally without leaking account existence.

The raw token appears only where required to construct/deliver the link. It is
never persisted and never logged by this module.
"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Protocol

from app.config import get_email_settings

logger = logging.getLogger(__name__)

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 465
GMAIL_SMTP_TIMEOUT_SECONDS = 10.0

RESET_SUBJECT = "Reset your Comic Pile password"
PRODUCTION_RESET_ORIGIN = "https://comic-pile.vercel.app"
NON_PRODUCTION_RESET_ORIGIN = "http://localhost:3000"


def build_password_reset_url(origin: str, path: str, raw_token: str) -> str:
    """Build the user-facing reset URL at the delivery boundary.

    Args:
        origin: Public web origin, e.g. ``https://app.example.com``.
        path: Public reset-page path, e.g. ``/reset-password``.
        raw_token: One-time raw reset token (never persisted or logged).

    Returns:
        Absolute reset URL carrying the token as a query parameter.
    """
    clean_origin = origin.strip().rstrip("/")
    clean_path = path.strip() or "/reset-password"
    if not clean_path.startswith("/"):
        clean_path = f"/{clean_path}"
    encoded_token = urllib.parse.quote(raw_token, safe="")
    return f"{clean_origin}{clean_path}?token={encoded_token}"


def build_password_reset_subject() -> str:
    """Return the password-reset email subject.

    Returns:
        Fixed subject line for reset messages.
    """
    return RESET_SUBJECT


def build_password_reset_text_body(
    username: str,
    reset_url: str,
    expires_at: datetime,
    expiry_minutes: int = 30,
) -> str:
    """Compose the minimal plaintext reset message.

    Args:
        username: Recipient username for greeting personalization.
        reset_url: Fully constructed reset link (delivery boundary only).
        expires_at: Token expiry timestamp for copy context.
        expiry_minutes: Human-readable expiry window in minutes.

    Returns:
        Plaintext email body with expiry and security language.
    """
    expiry_display = expires_at.strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"Hi {username},\n"
        "\n"
        "Someone requested a password reset for your Comic Pile account.\n"
        "Use the link below to choose a new password:\n"
        "\n"
        f"{reset_url}\n"
        "\n"
        f"This link expires in {expiry_minutes} minutes "
        f"(around {expiry_display}) and can be used only once.\n"
        "If you did not request a reset, you can safely ignore this message — "
        "your password has not changed.\n"
        "Never share this link with anyone; it grants access to your account.\n"
    )


class PasswordResetDeliveryError(Exception):
    """Raised when the outbound email provider fails to accept the message."""


@dataclass
class SentPasswordResetEmail:
    """Record of one delivered reset message (fake/test mailer)."""

    recipient_email: str
    subject: str
    body: str
    reset_url: str


class PasswordResetMailer(Protocol):
    """Provider-neutral mailer interface for password-reset delivery."""

    async def send_password_reset(
        self,
        *,
        recipient_email: str,
        username: str,
        reset_token: str,
        expires_at: datetime,
    ) -> None:
        """Deliver one password-reset message.

        Args:
            recipient_email: Destination mailbox.
            username: Recipient username for message personalization.
            reset_token: One-time raw token used only to build the link.
            expires_at: Token expiry timestamp for message copy.
        """
        ...


class FakePasswordResetMailer:
    """Deterministic in-memory mailer for tests and local development."""

    def __init__(self) -> None:
        """Initialize with an empty sent-message record."""
        self.sent: list[SentPasswordResetEmail] = []

    async def send_password_reset(
        self,
        *,
        recipient_email: str,
        username: str,
        reset_token: str,
        expires_at: datetime,
        expiry_minutes: int = 30,
    ) -> None:
        """Record one reset message instead of sending it.

        Args:
            recipient_email: Destination mailbox.
            username: Recipient username for message personalization.
            reset_token: One-time raw token used only to build the link.
            expires_at: Token expiry timestamp for message copy.
            expiry_minutes: Human-readable expiry window in minutes.
        """
        settings = get_email_settings()
        origin = settings.normalized_origin or NON_PRODUCTION_RESET_ORIGIN
        reset_url = build_password_reset_url(
            origin,
            settings.normalized_path,
            reset_token,
        )
        body = build_password_reset_text_body(
            username,
            reset_url,
            expires_at,
            expiry_minutes,
        )
        self.sent.append(
            SentPasswordResetEmail(
                recipient_email=recipient_email,
                subject=build_password_reset_subject(),
                body=body,
                reset_url=reset_url,
            )
        )

    def clear(self) -> None:
        """Discard all recorded messages."""
        self.sent.clear()


@dataclass
class GmailPasswordResetMailer:
    """Production Gmail SMTP adapter behind the provider-neutral boundary."""

    username: str
    app_password: str
    sender: str
    origin: str
    path: str = "/reset-password"
    expiry_minutes: int = 30
    timeout_seconds: float = GMAIL_SMTP_TIMEOUT_SECONDS
    smtp_host: str = GMAIL_SMTP_HOST
    smtp_port: int = GMAIL_SMTP_PORT

    def _build_message(
        self,
        *,
        recipient_email: str,
        username: str,
        reset_token: str,
        expires_at: datetime,
    ) -> EmailMessage:
        """Build one password-reset email without retaining the raw token."""
        reset_url = build_password_reset_url(self.origin, self.path, reset_token)
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient_email
        message["Subject"] = build_password_reset_subject()
        message.set_content(
            build_password_reset_text_body(
                username,
                reset_url,
                expires_at,
                self.expiry_minutes,
            )
        )
        return message

    def _send_message(self, message: EmailMessage) -> None:
        """Send one message through Gmail SMTP synchronously."""
        context = ssl.create_default_context()
        try:
            with smtplib.SMTP_SSL(
                self.smtp_host,
                self.smtp_port,
                timeout=self.timeout_seconds,
                context=context,
            ) as smtp:
                smtp.login(self.username, self.app_password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise PasswordResetDeliveryError(
                "Gmail SMTP rejected or failed to deliver the reset message.",
            ) from exc

    async def send_password_reset(
        self,
        *,
        recipient_email: str,
        username: str,
        reset_token: str,
        expires_at: datetime,
    ) -> None:
        """Deliver one password-reset message through Gmail SMTP."""
        message = self._build_message(
            recipient_email=recipient_email,
            username=username,
            reset_token=reset_token,
            expires_at=expires_at,
        )
        await asyncio.to_thread(self._send_message, message)
        logger.info(
            "Password reset email accepted by provider.",
            extra={"event": "password_reset_email_sent"},
        )


_fake_mailer: FakePasswordResetMailer | None = None

_mailer_override: PasswordResetMailer | None = None


def get_fake_mailer() -> FakePasswordResetMailer:
    """Return the shared deterministic fake mailer singleton.

    Returns:
        Process-wide fake mailer used when no provider is configured.
    """
    global _fake_mailer
    if _fake_mailer is None:
        _fake_mailer = FakePasswordResetMailer()
    return _fake_mailer


def override_password_reset_mailer(mailer: PasswordResetMailer | None) -> None:
    """Override mailer resolution (tests only).

    Args:
        mailer: Replacement mailer, or None to restore default resolution.
    """
    global _mailer_override
    _mailer_override = mailer


def _default_sender_and_origin(username: str) -> tuple[str, str]:
    """Return a Gmail sender identity and environment-appropriate public origin."""
    sender = f"Comic Pile <{username}>"
    if os.environ.get("ENVIRONMENT", "development") == "production":
        return sender, PRODUCTION_RESET_ORIGIN
    return sender, NON_PRODUCTION_RESET_ORIGIN


def get_password_reset_mailer() -> PasswordResetMailer:
    """Resolve the active password-reset mailer.

    Gmail SMTP requires the Gmail address plus a Google App Password. The sender
    defaults to that same Gmail identity, while PASSWORD_RESET_SENDER remains an
    optional override for an alias already configured on the Gmail account.
    """
    if _mailer_override is not None:
        return _mailer_override

    settings = get_email_settings()
    gmail_username = settings.usable_gmail_smtp_username
    gmail_app_password = settings.usable_gmail_smtp_app_password
    if not gmail_username or not gmail_app_password:
        return get_fake_mailer()

    default_sender, default_origin = _default_sender_and_origin(gmail_username)
    sender = settings.password_reset_sender.strip() or default_sender
    origin = settings.normalized_origin or default_origin
    return GmailPasswordResetMailer(
        username=gmail_username,
        app_password=gmail_app_password,
        sender=sender,
        origin=origin,
        path=settings.normalized_path,
    )
