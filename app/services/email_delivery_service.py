"""Email delivery service for password reset and other notifications."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypedDict

import httpx

from app.config import EmailSettings, get_app_settings, get_email_settings
from app.services.password_reset_service import PasswordResetDeliveryHandoff

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
RESET_PASSWORD_PATH = "/reset-password"
DEV_PASSWORD_RESET_SENDER_EMAIL = "noreply@localhost"


class EmailDeliveryError(Exception):
    """Exception raised when email delivery fails."""


def resolve_sender_email(settings: EmailSettings) -> str:
    """Resolve the sender address, refusing to invent a production sender.

    A Resend sender must be an address on a domain verified in Resend, which is
    owner-controlled configuration. Falling back to a built-in address would
    silently produce provider rejections, so an unconfigured sender fails closed
    with a clear operational error instead.

    Args:
        settings: Email delivery settings for the current environment.

    Returns:
        The configured sender address, or the local-development fallback when no
        provider is configured.

    Raises:
        EmailDeliveryError: When Resend is configured but no sender address is.
    """
    if settings.password_reset_sender_email:
        return settings.password_reset_sender_email
    if settings.is_resend_configured:
        raise EmailDeliveryError(
            "PASSWORD_RESET_SENDER_EMAIL is not configured; set it to an address "
            "on a Resend-verified sending domain"
        )
    return DEV_PASSWORD_RESET_SENDER_EMAIL


def build_reset_url(reset_origin: str, reset_token: str) -> str:
    """Build the single user-facing password reset URL.

    This is the only place the raw one-time token is turned into a link. The
    token is never returned, stored, or logged.

    Args:
        reset_origin: Public origin that serves the reset page.
        reset_token: Raw one-time reset token from the delivery handoff.

    Returns:
        Absolute reset URL containing the one-time token.
    """
    return f"{reset_origin.rstrip('/')}{RESET_PASSWORD_PATH}?token={reset_token}"


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
        reset_url = build_reset_url(reset_origin, handoff.reset_token)
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

    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 10.0,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        """Initialize the Resend email provider.

        Args:
            api_key: Resend API key for authentication.
            timeout_seconds: Outbound request timeout in seconds.
            client_factory: Optional factory for the outbound HTTP client.
                Defaults to a real ``httpx.AsyncClient``; tests inject a client
                backed by a mock transport.
        """
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._client_factory = client_factory

    def _build_client(self) -> httpx.AsyncClient:
        """Build the outbound HTTP client for a delivery attempt."""
        if self._client_factory is not None:
            return self._client_factory()
        return httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds))

    async def send_password_reset_email(
        self,
        handoff: PasswordResetDeliveryHandoff,
        sender_email: str,
        sender_name: str,
        reset_origin: str,
    ) -> PasswordResetDeliveryResult:
        """Send a password reset email using Resend."""
        reset_url = build_reset_url(reset_origin, handoff.reset_token)
        payload = {
            "from": f"{sender_name} <{sender_email}>",
            "to": [handoff.recipient_email],
            "subject": "Reset your Comic Pile password",
            "text": _render_reset_email_body(handoff.user_username, reset_url, handoff.expires_at),
        }
        try:
            async with self._build_client() as client:
                response = await client.post(
                    RESEND_API_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
            delivery = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.error(
                "Failed to send password reset email via Resend: %s",
                type(exc).__name__,
                extra={
                    "event": "resend_email_failure",
                    "user": handoff.user_username,
                },
            )
            raise EmailDeliveryError("Failed to send password reset email") from exc

        message_id = str(delivery.get("id", "")) if isinstance(delivery, dict) else ""
        logger.info(
            "Password reset email sent via Resend",
            extra={
                "event": "resend_email_sent",
                "user": handoff.user_username,
                "message_id": message_id,
            },
        )
        metadata: ResetEmailMetadata = {
            "user_username": handoff.user_username,
            "expires_at": handoff.expires_at.isoformat(),
            "created_at": datetime.now(UTC).isoformat(),
        }
        return {
            "status": "sent",
            "provider": "resend",
            "recipients": [handoff.recipient_email],
            "message_id": message_id,
            "metadata": metadata,
        }


class EmailDeliveryService:
    """Email delivery service that manages provider selection and delivery."""

    def __init__(self, provider: EmailDeliveryProvider | None = None) -> None:
        """Initialize the email delivery service.

        Args:
            provider: Optional email delivery provider. If None, uses configured provider.
        """
        self._provider = provider
        self._fake_provider: FakeEmailProvider | None = None

    def _get_provider(self) -> EmailDeliveryProvider:
        """Resolve the provider for the current configuration.

        Returns:
            Configured provider instance.

        Raises:
            EmailDeliveryError: If the provider is required but not configured.
        """
        if self._provider is not None:
            return self._provider

        settings = get_email_settings()
        if not settings.is_resend_configured:
            if get_app_settings().environment == "production":
                raise EmailDeliveryError("RESEND_API_KEY is not configured")
            logger.warning("Resend not configured, using fake email provider")
            if self._fake_provider is None:
                self._fake_provider = FakeEmailProvider()
            return self._fake_provider

        api_key = settings.resend_api_key
        if not api_key:
            raise EmailDeliveryError("RESEND_API_KEY is not configured")
        return ResendEmailProvider(
            api_key=api_key,
            timeout_seconds=settings.email_delivery_timeout_seconds,
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
            EmailDeliveryError: If the provider is unconfigured, the sender
                address is missing while Resend is configured, or delivery fails.
        """
        settings = get_email_settings()
        provider = self._get_provider()
        return await provider.send_password_reset_email(
            handoff=handoff,
            sender_email=resolve_sender_email(settings),
            sender_name=settings.password_reset_sender_name,
            reset_origin=settings.password_reset_origin,
        )


# Global email delivery service instance
_email_service: EmailDeliveryService | None = None


def get_email_delivery_service() -> EmailDeliveryService:
    """Get the global email delivery service instance."""
    global _email_service
    if _email_service is None:
        _email_service = EmailDeliveryService()
    return _email_service


async def deliver_password_reset_handoff(
    handoff: PasswordResetDeliveryHandoff | None,
    service: EmailDeliveryService | None = None,
) -> PasswordResetDeliveryResult | None:
    """Deliver a password reset handoff without leaking account existence.

    Unknown addresses produce no handoff and no delivery attempt, and provider
    failures are contained so the caller always returns the same enumeration-safe
    acknowledgement. The raw reset token is never logged.

    Args:
        handoff: Provider-neutral handoff from the password reset service, or
            None when the address is unknown.
        service: Optional delivery service override. Defaults to the shared
            instance.

    Returns:
        The delivery outcome, or None when nothing was delivered.
    """
    if handoff is None:
        return None

    delivery_service = service if service is not None else get_email_delivery_service()
    try:
        result = await delivery_service.send_password_reset_email(handoff)
    except Exception as exc:
        # EmailDeliveryError messages are fixed, token-free strings raised by this
        # module, so the reason is safe to log. Anything else is reported by type
        # only so provider payloads never reach the log.
        reason = str(exc) if isinstance(exc, EmailDeliveryError) else type(exc).__name__
        logger.error(
            "Password reset email delivery failed: %s",
            reason,
            extra={
                "event": "password_reset_email_failure",
                "user": handoff.user_username,
                "failure": reason,
            },
        )
        return None

    logger.info(
        "Password reset email delivered: user=%s provider=%s status=%s",
        handoff.user_username,
        result["provider"],
        result["status"],
        extra={
            "event": "password_reset_email_sent",
            "user": handoff.user_username,
            "provider": result["provider"],
            "status": result["status"],
        },
    )
    return result
