#!/usr/bin/env python3
"""Simple test script for email delivery functionality."""

import asyncio
from datetime import datetime, UTC, timedelta
from typing import Any, Dict
from abc import ABC, abstractmethod


class PasswordResetDeliveryHandoff:
    """Mock version of PasswordResetDeliveryHandoff for testing."""
    
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
        """Send a password reset email."""
        pass


class FakeEmailProvider(EmailDeliveryProvider):
    """Fake email provider for testing and development."""

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

        return {
            "status": "sent",
            "provider": "fake",
            "recipients": [handoff.recipient_email],
            "message_id": f"fake-{id(email_data)}",
            "metadata": email_data["metadata"],
        }


class EmailDeliveryService:
    """Email delivery service that manages provider selection and delivery."""

    def __init__(self, provider: EmailDeliveryProvider | None = None) -> None:
        """Initialize the email delivery service."""
        self._provider = provider

    def _get_provider(self) -> EmailDeliveryProvider:
        """Get the email delivery provider."""
        if self._provider is not None:
            return self._provider

        # Use fake provider by default (for development/testing)
        return FakeEmailProvider()

    async def send_password_reset_email(
        self,
        handoff: PasswordResetDeliveryHandoff,
    ) -> Dict[str, Any]:
        """Send a password reset email using the configured provider."""
        provider = self._get_provider()
        
        return await provider.send_password_reset_email(
            handoff=handoff,
            sender_email="noreply@comicpile.app",
            sender_name="Comic Pile",
            reset_origin="https://comicpile.app",
        )


async def test_fake_email_provider():
    """Test the fake email provider."""
    print("Testing FakeEmailProvider...")
    
    provider = FakeEmailProvider()
    
    # Create a test handoff
    handoff = PasswordResetDeliveryHandoff(
        recipient_email="test@example.com",
        user_username="testuser",
        reset_token="fake-token-123",
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    
    # Send email
    result = await provider.send_password_reset_email(
        handoff=handoff,
        sender_email="noreply@comicpile.app",
        sender_name="Comic Pile",
        reset_origin="https://comicpile.app",
    )
    
    # Verify result
    assert result["status"] == "sent"
    assert result["provider"] == "fake"
    assert result["recipients"] == ["test@example.com"]
    assert "message_id" in result
    assert "metadata" in result
    assert result["metadata"]["user_username"] == "testuser"
    assert result["metadata"]["reset_token"] == "fake-token-123"
    
    # Verify email was stored
    assert len(provider.sent_emails) == 1
    email = provider.sent_emails[0]
    assert email["to"] == "test@example.com"
    assert email["from"] == "Comic Pile <noreply@comicpile.app>"
    assert email["subject"] == "Reset your Comic Pile password"
    assert "Hello testuser" in email["text"]
    assert "https://comicpile.app/reset-password?token=fake-token-123" in email["text"]
    assert "This link will expire at" in email["text"]
    
    print("✅ FakeEmailProvider test passed")


async def test_email_delivery_service():
    """Test the email delivery service."""
    print("Testing EmailDeliveryService...")
    
    # Test with fake provider
    service = EmailDeliveryService()
    provider = service._get_provider()
    
    assert isinstance(provider, FakeEmailProvider)
    
    # Test with custom provider
    custom_provider = FakeEmailProvider()
    service = EmailDeliveryService(provider=custom_provider)
    assert service._get_provider() is custom_provider
    
    print("✅ EmailDeliveryService test passed")


async def test_end_to_end():
    """Test end-to-end email delivery."""
    print("Testing end-to-end email delivery...")
    
    provider = FakeEmailProvider()
    service = EmailDeliveryService(provider=provider)
    
    handoff = PasswordResetDeliveryHandoff(
        recipient_email="e2e@example.com",
        user_username="e2euser",
        reset_token="e2e-token",
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    
    result = await service.send_password_reset_email(handoff)
    
    assert result["status"] == "sent"
    assert result["provider"] == "fake"
    assert len(provider.sent_emails) == 1
    email = provider.sent_emails[0]
    assert email["to"] == "e2e@example.com"
    assert "Hello e2euser" in email["text"]
    assert "https://comicpile.app/reset-password?token=e2e-token" in email["text"]
    
    print("✅ End-to-end test passed")


async def test_reset_url_construction():
    """Test that reset URLs are constructed correctly."""
    print("Testing reset URL construction...")
    
    provider = FakeEmailProvider()
    
    # Test with different origins
    test_cases = [
        ("https://comicpile.app", "https://comicpile.app/reset-password?token=test123"),
        ("https://staging.comicpile.app", "https://staging.comicpile.app/reset-password?token=test123"),
        ("http://localhost:3000", "http://localhost:3000/reset-password?token=test123"),
    ]
    
    for origin, expected_url in test_cases:
        handoff = PasswordResetDeliveryHandoff(
            recipient_email="urltest@example.com",
            user_username="urluser",
            reset_token="test123",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        
        await provider.send_password_reset_email(
            handoff=handoff,
            sender_email="noreply@comicpile.app",
            sender_name="Comic Pile",
            reset_origin=origin,
        )
        
        email = provider.sent_emails[-1]  # Get the last email
        assert expected_url in email["text"]
    
    print("✅ Reset URL construction test passed")


async def test_multiple_emails():
    """Test that multiple emails are handled correctly."""
    print("Testing multiple emails...")
    
    provider = FakeEmailProvider()
    
    # Send multiple emails
    for i in range(3):
        handoff = PasswordResetDeliveryHandoff(
            recipient_email=f"user{i}@example.com",
            user_username=f"user{i}",
            reset_token=f"token-{i}",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        
        await provider.send_password_reset_email(
            handoff=handoff,
            sender_email="noreply@comicpile.app",
            sender_name="Comic Pile",
            reset_origin="https://comicpile.app",
        )
    
    # Verify all emails stored
    assert len(provider.sent_emails) == 3
    for i, email in enumerate(provider.sent_emails):
        assert email["to"] == f"user{i}@example.com"
        assert f"Hello user{i}" in email["text"]
        assert f"token-{i}" in email["text"]
    
    print("✅ Multiple emails test passed")


async def test_email_content():
    """Test email content is correct."""
    print("Testing email content...")
    
    provider = FakeEmailProvider()
    
    handoff = PasswordResetDeliveryHandoff(
        recipient_email="content@example.com",
        user_username="contentuser",
        reset_token="content-token",
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    
    await provider.send_password_reset_email(
        handoff=handoff,
        sender_email="noreply@comicpile.app",
        sender_name="Comic Pile",
        reset_origin="https://comicpile.app",
    )
    
    email = provider.sent_emails[0]
    
    # Check content
    assert "Hello contentuser" in email["text"]
    assert "Reset your Comic Pile password" in email["subject"]
    assert "You requested a password reset" in email["text"]
    assert "Click the link below to reset your password" in email["text"]
    assert "This link will expire at" in email["text"]
    assert "If you didn't request this reset, please ignore this email" in email["text"]
    assert "Thanks," in email["text"]
    assert "The Comic Pile Team" in email["text"]
    
    print("✅ Email content test passed")


async def run_all_tests():
    """Run all tests."""
    print("🧪 Running email delivery tests...\n")
    
    try:
        await test_fake_email_provider()
        await test_email_delivery_service()
        await test_end_to_end()
        await test_reset_url_construction()
        await test_multiple_emails()
        await test_email_content()
        
        print("\n🎉 All tests passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)