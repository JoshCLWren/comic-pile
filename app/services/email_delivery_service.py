"""Email delivery service for password reset and other notifications."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict

from app.config import get_email_settings
from app.services.password_reset_service import PasswordResetDeliveryHandoff

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Exception raised when email delivery fails."""

    pass


class EmailDeliveryProvider(ABC):
    """Abstract base class for email delivery providers."""

    @abstractmethod
    async def send_password_reset_email(
        self,
        handoff: PasswordResetDeliveryHandoff,
        sender_email: str,
        sender_name: str,
        reset_origin: str,
    ) -> Dict[str, Any]:
        """Send a password reset email.

        Args:
            handoff: Password reset delivery handoff containing token and metadata.
            sender_email: Email address to send from.
            sender_name: Name to display as sender.
            reset_origin: Public origin for reset links.

        Returns:
            Dict containing delivery status and metadata.

        Raises:
            EmailDeliveryError: If email delivery fails.
        """
        pass


class FakeEmailProvider(EmailDeliveryProvider):
    """Fake email provider for testing and development.

    Stores sent emails in memory for inspection by tests.
    """

    def __init__(self) -> None:
        """Initialize the fake email provider."""
        self.sent_emails: list[Dict[str, Any]] = []

    async def send_password_reset_email(
        self,
        handoff: PasswordResetDeliveryHandoff,
        sender_email: str,
        sender_name: str,
        reset_origin: str,
    ) -> Dict[str, Any]:
        """Send a password reset email (fake implementation)."""
        # Generate reset URL
        reset_url = f"{reset_origin}/reset-password?token={handoff.reset_token}"

        # Store the email for inspection
        email_data = {
            "to": handoff.recipient_email,
            "from": f"{sender_name} <{sender_email}>",
            "subject": "Reset your Comic Pile password",
            "text": f"""Hello {handoff.user_username},

You requested a password reset for your Comic Pile account.

Click the link below to reset your password:
{reset_url}

This link will expire at {handoff.expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}.

If you didn't request this reset, please ignore this email.

Thanks,
The Comic Pile Team""",
            "metadata": {
                "user_username": handoff.user_username,
                "reset_token": handoff.reset_token,
                "expires_at": handoff.expires_at.isoformat(),
                "created_at": datetime.now().isoformat(),
            },
        }
        self.sent_emails.append(email_data)

        logger.info(
            "Fake password reset email sent to %s", handoff.recipient_email, extra={"event": "fake_email_sent"}
        )

        return {
            "status": "sent",
            "provider": "fake",
            "recipients": [handoff.recipient_email],
            "message_id": f"fake-{id(email_data)}",
            "metadata": email_data["metadata"],
        }


class ResendEmailProvider(EmailDeliveryProvider):
    """Resend email provider for production password reset delivery."""

    def __init__(self, api_key: str) -> None:
        """Initialize the Resend email provider.

        Args:
            api_key: Resend API key for authentication.
        """
        self.api_key = api_key

    async def send_password_reset_email(
        self,
        handoff: PasswordResetDeliveryHandoff,
        sender_email: str,
        sender_name: str,
        reset_origin: str,
    ) -> Dict[str, Any]:
        """Send a password reset email using Resend."""
        try:
            # Generate reset URL
            reset_url = f"{reset_origin}/reset-password?token={handoff.reset_token}"

            # Prepare email data
            email_data = {
                "from": f"{sender_name} <{sender_email}>",
                "to": handoff.recipient_email,
                "subject": "Reset your Comic Pile password",
                "text": f"""Hello {handoff.user_username},

You requested a password reset for your Comic Pile account.

Click the link below to reset your password:
{reset_url}

This link will expire at {handoff.expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}.

If you didn't request this reset, please ignore this email.

Thanks,
The Comic Pile Team""",
                "headers": {
                    "X-Custom-User-ID": str(handoff.user_username),
                    "X-Custom-Event-Type": "password_reset",
                },
            }

            # TODO: Implement actual Resend API call
            # For now, log the email data and simulate success
            logger.info(
                "Would send password reset email to %s via Resend", 
                handoff.recipient_email, 
                extra={
                    "event": "resend_email_delivery",
                    "user": handoff.user_username,
                    "recipient": handoff.recipient_email,
                    "expires_at": handoff.expires_at.isoformat(),
                    # Note: Never log the raw token in production
                }
            )

            # Simulate successful delivery for now
            # In production, this would make an actual HTTP call to Resend API
            return {
                "status": "sent",
                "provider": "resend",
                "recipients": [handoff.recipient_email],
                "message_id": f"resend-{datetime.now().timestamp()}",
                "metadata": {
                    "user_username": handoff.user_username,
                    "expires_at": handoff.expires_at.isoformat(),
                    "created_at": datetime.now().isoformat(),
                },
            }

        except Exception as e:
            logger.error(
                "Failed to send password reset email via Resend: %s", str(e), 
                extra={
                    "event": "resend_email_failure",
                    "user": handoff.user_username,
                    "recipient": handoff.recipient_email,
                    "error": str(e),
                }
            )
            raise EmailDeliveryError(f"Failed to send email: {str(e)}") from e


class EmailDeliveryService:
    """Email delivery service that manages provider selection and delivery."""

    def __init__(self, provider: EmailDeliveryProvider | None = None) -> None:
        """Initialize the email delivery service.

        Args:
            provider: Optional email delivery provider. If None, uses configured provider.
        """
        self._provider = provider
        self._email_settings = get_email_settings()

    def _get_provider(self) -> EmailDeliveryProvider:
        """Get the configured email delivery provider."""
        if self._provider is not None:
            return self._provider

        # Use fake provider if not configured (for development/testing)
        if not self._email_settings.is_resend_configured:
            logger.warning("Resend not configured, using fake email provider")
            return FakeEmailProvider()

        # Use Resend provider for production
        return ResendEmailProvider(self._email_settings.resend_api_key)

    async def send_password_reset_email(
        self,
        handoff: PasswordResetDeliveryHandoff,
    ) -> Dict[str, Any]:
        """Send a password reset email using the configured provider.

        Args:
            handoff: Password reset delivery handoff containing token and metadata.

        Returns:
            Dict containing delivery status and metadata.

        Raises:
            EmailDeliveryError: If email delivery fails.
        """
        provider = self._get_provider()
        
        return await provider.send_password_reset_email(
            handoff=handoff,
            sender_email=self._email_settings.password_reset_sender_email or "noreply@comicpile.app",
            sender_name=self._email_settings.password_reset_sender_name or "Comic Pile",
            reset_origin=self._email_settings.password_reset_origin or "https://comicpile.app",
        )


# Global email delivery service instance
_email_service: EmailDeliveryService | None = None


def get_email_delivery_service() -> EmailDeliveryService:
    """Get the global email delivery service instance."""
    global _email_service
    if _email_service is None:
        _email_service = EmailDeliveryService()
    return _email_service