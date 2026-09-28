"""Email delivery service for password reset and other notifications."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TypedDict

import httpx

from app.config import get_email_settings
from app.services.password_reset_service import PasswordResetDeliveryHandoff

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class EmailDeliveryError(Exception):
    """Exception raised when email delivery fails."""


class ResetEmailMetadata(TypedDict):
    """Non-sensitive delivery metadata returned by email providers."""

    user_username: str
    expires_at: str
    created_at: str


class SentEmail(TypedDict):
    """Stored record of an email accepted by the fake provider."""

    to: str
    sender: str
    subject: str
    text: str
    metadata: ResetEmailMetadata


class PasswordResetDeliveryResult(TypedDict):
    """Delivery outcome returned by email providers."""

    status: str
    provider: str
    recipients: list[str]
    message_id: str
    metadata: ResetEmailMetadata


def _render_reset_email_body(user_username: str, reset_url: str, expires_at: datetime) -> str:
    """Render the plain-text password reset email body.

    Args:
        user_username: Username shown in the greeting.
        reset_url: One-time reset link containing the raw token.
        expires_at: Token expiry timestamp shown in the expiry copy.

    Returns:
        Plain-text email body with reset link and expiry language.
    """
    return f"""Hello {user_username},

You requested a password reset for your Comic Pile account.

Click the link below to reset your password:
{reset_url}

This link will expire at {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}.

If you didn't request this reset, please ignore this email.

Thanks,
The Comic Pile Team"""


class EmailDeliveryProvider(ABC):
    """Abstract base class for email delivery providers."""

    @abstractmethod
    async def send_password_reset_email(
        self,
        handoff: PasswordResetDeliveryHandoff,
        sender_email: str,
        sender_name: str,
        reset_origin: str,
    ) -> PasswordResetDeliveryResult:
        """Send a password reset email.

        Args:
            handoff: Password reset delivery handoff containing token and metadata.
            sender_email: Email address to send from.
            sender_name: Name to display as sender.
            reset_origin: Public origin for reset links.

        Returns:
            Delivery outcome with status, provider, and non-sensitive metadata.

        Raises:
            EmailDeliveryError: If email delivery fails.
        """


class FakeEmailProvider(EmailDeliveryProvider):
    """Fake email provider for testing and development.

    Stores sent emails in memory for inspection by tests.
    """

    def __init__(self) -> None:
        """Initialize the fake email provider."""
        self.sent_emails: list[SentEmail] = []

    async def send_password_reset_email(
        self,
        handoff: PasswordResetDeliveryHandoff,
        sender_email: str,
        sender_name: str,
        reset_origin: str,
    ) -> PasswordResetDeliveryResult:
        """Send a password reset email (fake implementation)."""
        reset_url = f"{reset_origin}/reset-password?token={handoff.reset_token}"
        metadata: ResetEmailMetadata = {
            "user_username": handoff.user_username,
            "expires_at": handoff.expires_at.isoformat(),
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.sent_emails.append(
            {
                "to": handoff.recipient_email,
                "sender": f"{sender_name} <{sender_email}>",
                "subject": "Reset your Comic Pile password",
                "text": _render_reset_email_body(handoff.user_username, reset_url, handoff.expires_at),
                "metadata": metadata,
            }
        )
        logger.info(
            "Fake password reset email sent to %s",
            handoff.recipient_email,
            extra={"event": "fake_email_sent"},
        )
        return {
            "status": "sent",
            "provider": "fake",
            "recipients": [handoff.recipient_email],
            "message_id": f"fake-{len(self.sent_emails)}",
            "metadata": metadata,
        }


class ResendEmailProvider(EmailDeliveryProvider):
    """Resend email provider for production password reset delivery."""

    def __init__(self, api_key: str, timeout_seconds: float = 10.0) -> None:
        """Initialize the Resend email provider.

        Args:
            api_key: Resend API key for authentication.
            timeout_seconds: Outbound request timeout in seconds.
        """
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def send_password_reset_email(
        self,
        handoff: PasswordResetDeliveryHandoff,
        sender_email: str,
        sender_name: str,
        reset_origin: str,
    ) -> PasswordResetDeliveryResult:
        """Send a password reset email using Resend."""
        reset_url = f"{reset_origin}/reset-password?token={handoff.reset_token}"
        payload = {
            "from": f"{sender_name} <{sender_email}>",
            "to": handoff.recipient_email,
            "subject": "Reset your Comic Pile password",
            "text": _render_reset_email_body(handoff.user_username, reset_url, handoff.expires_at),
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                headers={"Authorization": f"Bearer {self.api_key}"},
            ) as client:
                response = await client.post(RESEND_API_URL, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error(
                "Failed to send password reset email via Resend: %s",
                exc,
                extra={
                    "event": "resend_email_failure",
                    "user": handoff.user_username,
                    "recipient": handoff.recipient_email,
                },
            )
            raise EmailDeliveryError("Failed to send password reset email") from exc

        delivery = response.json()
        message_id = str(delivery.get("id", ""))
        logger.info(
            "Password reset email sent via Resend",
            extra={
                "event": "resend_email_sent",
                "user": handoff.user_username,
                "message_id": message_id,
            },
        )
        return {
            "status": "sent",
            "provider": "resend",
            "recipients": [handoff.recipient_email],
            "message_id": message_id,
            "metadata": {
                "user_username": handoff.user_username,
                "expires_at": handoff.expires_at.isoformat(),
                "created_at": datetime.now(UTC).isoformat(),
            },
        }


class EmailDeliveryService:
    """Email delivery service that manages provider selection and delivery."""

    def __init__(self, provider: EmailDeliveryProvider | None = None) -> None:
        """Initialize the email delivery service.

        Args:
            provider: Optional email delivery provider. If None, uses configured provider.
        """
        self._provider = provider
        self._email_settings = get_email_settings()
        self._fake_provider: FakeEmailProvider | None = None

    def _get_provider(self) -> EmailDeliveryProvider:
        """Get the configured email delivery provider."""
        if self._provider is not None:
            return self._provider

        if not self._email_settings.is_resend_configured:
            logger.warning("Resend not configured, using fake email provider")
            if self._fake_provider is None:
                self._fake_provider = FakeEmailProvider()
            return self._fake_provider

        api_key = self._email_settings.resend_api_key
        assert api_key is not None, "Resend configured without an API key"
        return ResendEmailProvider(
            api_key=api_key,
            timeout_seconds=self._email_settings.email_delivery_timeout_seconds,
        )

    async def send_password_reset_email(
        self,
        handoff: PasswordResetDeliveryHandoff,
    ) -> PasswordResetDeliveryResult:
        """Send a password reset email using the configured provider.

        Args:
            handoff: Password reset delivery handoff containing token and metadata.

        Returns:
            Delivery outcome with status, provider, and non-sensitive metadata.

        Raises:
            EmailDeliveryError: If email delivery fails.
        """
        provider = self._get_provider()
        return await provider.send_password_reset_email(
            handoff=handoff,
            sender_email=self._email_settings.password_reset_sender_email,
            sender_name=self._email_settings.password_reset_sender_name,
            reset_origin=self._email_settings.password_reset_origin,
        )


# Global email delivery service instance
_email_service: EmailDeliveryService | None = None


def get_email_delivery_service() -> EmailDeliveryService:
    """Get the global email delivery service instance."""
    global _email_service
    if _email_service is None:
        _email_service = EmailDeliveryService()
    return _email_service
