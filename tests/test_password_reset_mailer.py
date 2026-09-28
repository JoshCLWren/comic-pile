"""Focused acceptance tests for #2778 password-reset email delivery."""

import hashlib
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.auth import hash_password
from app.config import clear_settings_cache, get_email_settings
from app.repositories.user_repository import create_user, get_user_by_username
from app.services.password_reset_mailer import (
    FakePasswordResetMailer,
    PasswordResetDeliveryError,
    ResendPasswordResetMailer,
    build_password_reset_text_body,
    build_password_reset_url,
    get_fake_mailer,
    get_password_reset_mailer,
    override_password_reset_mailer,
)
from app.services.password_reset_service import (
    TOKEN_EXPIRY_MINUTES,
    complete_reset,
    request_forgot_password,
)


@pytest.fixture
def _clean_mailer_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate mailer singletons and email settings between tests."""
    for var in (
        "RESEND_API_KEY",
        "PASSWORD_RESET_SENDER",
        "PASSWORD_RESET_ORIGIN",
        "PASSWORD_RESET_PATH",
    ):
        monkeypatch.delenv(var, raising=False)
    clear_settings_cache()
    override_password_reset_mailer(None)
    get_fake_mailer().clear()
    yield
    override_password_reset_mailer(None)
    get_fake_mailer().clear()
    clear_settings_cache()


def test_build_password_reset_url_normalizes_and_encodes_token() -> None:
    """Origin slashes are normalized and the token is query-encoded."""
    url = build_password_reset_url(
        "https://app.example.com/",
        "reset-password",
        "a+b/c=d e",
    )
    assert url.startswith("https://app.example.com/reset-password?token=")
    parsed = urllib.parse.urlparse(url)
    recovered = urllib.parse.parse_qs(parsed.query)["token"][0]
    assert recovered == "a+b/c=d e"


def test_reset_body_contains_expiry_and_security_copy() -> None:
    """The message carries expiry language and single-use/ignore guidance."""
    expires_at = datetime.now(UTC) + timedelta(minutes=TOKEN_EXPIRY_MINUTES)
    body = build_password_reset_text_body(
        "someuser",
        "https://app.example.com/reset-password?token=abc",
        expires_at,
    )
    assert f"{TOKEN_EXPIRY_MINUTES} minutes" in body
    assert "only once" in body
    assert "ignore" in body
    assert "Never share this link" in body


@pytest.mark.asyncio
async def test_fake_mailer_records_deterministic_message(
    _clean_mailer_state: None,
) -> None:
    """The fake adapter records subject, body, recipient, and link."""
    fake = FakePasswordResetMailer()
    expires_at = datetime.now(UTC) + timedelta(minutes=TOKEN_EXPIRY_MINUTES)
    await fake.send_password_reset(
        recipient_email="user@example.com",
        username="someuser",
        reset_token="raw-token-123",
        expires_at=expires_at,
    )
    assert len(fake.sent) == 1
    message = fake.sent[0]
    assert message.recipient_email == "user@example.com"
    assert message.subject
    assert f"{TOKEN_EXPIRY_MINUTES} minutes" in message.body
    assert "raw-token-123" in message.reset_url
    assert "raw-token-123" in message.body


@pytest.mark.asyncio
async def test_resend_adapter_sends_configured_payload_without_logging_token(
    _clean_mailer_state: None,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resend payload uses configured sender/origin and never logs the token."""
    captured: dict[str, object] = {}

    def _fake_post(self: ResendPasswordResetMailer, payload: dict[str, object]) -> int:
        """Capture the payload instead of hitting the network."""
        captured.update(payload)
        return 202

    monkeypatch.setattr(ResendPasswordResetMailer, "_post_payload", _fake_post)
    raw_token = "super-secret-raw-token"
    mailer = ResendPasswordResetMailer(
        api_key="re_test_key",
        sender="Comic Pile <no-reply@example.com>",
        origin="https://app.example.com",
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=TOKEN_EXPIRY_MINUTES)
    with caplog.at_level(logging.INFO, logger="app.services.password_reset_mailer"):
        await mailer.send_password_reset(
            recipient_email="user@example.com",
            username="someuser",
            reset_token=raw_token,
            expires_at=expires_at,
        )
    assert captured["from"] == "Comic Pile <no-reply@example.com>"
    assert captured["to"] == ["user@example.com"]
    assert isinstance(captured["subject"], str) and captured["subject"]
    body = captured["text"]
    assert isinstance(body, str)
    assert f"{TOKEN_EXPIRY_MINUTES} minutes" in body
    # Raw token appears exactly once: inside the delivered link.
    assert body.count(raw_token) == 1
    url_lines = [line for line in body.splitlines() if "token=" in line]
    assert len(url_lines) == 1
    assert raw_token in url_lines[0]
    for record in caplog.records:
        assert raw_token not in record.getMessage()
        assert raw_token not in str(record.args)


@pytest.mark.asyncio
async def test_resend_provider_failure_raises_without_token_in_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transport and HTTP failures surface as delivery errors, token-free."""
    def _raise_http(
        request: urllib.request.Request,
        timeout: float = 10.0,
    ) -> object:
        """Simulate a provider HTTP rejection."""
        raise urllib.error.HTTPError(
            "https://api.resend.com/emails",
            400,
            "Bad Request",
            {},
            None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", _raise_http)
    mailer = ResendPasswordResetMailer(
        api_key="re_test_key",
        sender="Comic Pile <no-reply@example.com>",
        origin="https://app.example.com",
    )
    with pytest.raises(PasswordResetDeliveryError) as exc_info:
        await mailer.send_password_reset(
            recipient_email="user@example.com",
            username="someuser",
            reset_token="token-that-must-not-leak",
            expires_at=datetime.now(UTC) + timedelta(minutes=TOKEN_EXPIRY_MINUTES),
        )
    assert "token-that-must-not-leak" not in str(exc_info.value)


def test_mailer_resolution_prefers_resend_when_configured_else_fake(
    _clean_mailer_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured settings resolve Resend; otherwise the deterministic fake."""
    assert isinstance(get_password_reset_mailer(), FakePasswordResetMailer)
    monkeypatch.setenv("RESEND_API_KEY", "re_live_key")
    monkeypatch.setenv("PASSWORD_RESET_SENDER", "Comic Pile <no-reply@example.com>")
    monkeypatch.setenv("PASSWORD_RESET_ORIGIN", "https://app.example.com")
    clear_settings_cache()
    mailer = get_password_reset_mailer()
    assert isinstance(mailer, ResendPasswordResetMailer)
    assert mailer.sender == "Comic Pile <no-reply@example.com>"
    assert mailer.origin == "https://app.example.com"
    assert mailer.api_key == "re_live_key"


def test_placeholder_api_key_counts_as_unconfigured(
    _clean_mailer_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Placeholder secrets never activate the production adapter."""
    monkeypatch.setenv("RESEND_API_KEY", "redacted")
    monkeypatch.setenv("PASSWORD_RESET_SENDER", "Comic Pile <no-reply@example.com>")
    monkeypatch.setenv("PASSWORD_RESET_ORIGIN", "https://app.example.com")
    clear_settings_cache()
    assert get_email_settings().is_configured is False
    assert isinstance(get_password_reset_mailer(), FakePasswordResetMailer)


@pytest.mark.asyncio
async def test_domain_stores_digest_only_never_plaintext(
    _clean_mailer_state: None,
    async_db,
) -> None:
    """The persisted token row holds a digest; the raw token is not stored."""
    user = await get_user_by_username(async_db, "maildigestuser")
    if user is None:
        user = await create_user(
            async_db,
            username="maildigestuser",
            email="digest@example.com",
            password_hash=hash_password("pw"),
        )
        await async_db.commit()
    handoff = await request_forgot_password(async_db, "digest@example.com")
    assert handoff is not None
    expected_digest = hashlib.sha256(handoff.reset_token.encode()).hexdigest()
    from sqlalchemy import select

    from app.models.password_reset_token import PasswordResetToken

    rows = (
        await async_db.execute(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id),
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].token_digest == expected_digest
    assert handoff.reset_token != expected_digest
    assert handoff.reset_token not in (rows[0].token_digest,)


@pytest.mark.asyncio
async def test_delivery_failure_keeps_enumeration_safety_and_token_state(
    _clean_mailer_state: None,
    client: AsyncClient,
    async_db,
) -> None:
    """A mail outage returns the identical ack and preserves token state."""

    class _FailingMailer:
        """Test double simulating a provider outage."""

        async def send_password_reset(
            self,
            *,
            recipient_email: str,
            username: str,
            reset_token: str,
            expires_at: datetime,
        ) -> None:
            """Always fail delivery without leaking account existence."""
            raise PasswordResetDeliveryError("provider down")

    override_password_reset_mailer(_FailingMailer())
    user = await get_user_by_username(async_db, "mailfailuser")
    if user is None:
        user = await create_user(
            async_db,
            username="mailfailuser",
            email="mailfail@example.com",
            password_hash=hash_password("pw"),
        )
        await async_db.commit()
    known = await client.post(
        "/api/auth/forgot-password",
        json={"email": "mailfail@example.com"},
    )
    unknown = await client.post(
        "/api/auth/forgot-password",
        json={"email": "definitely-unknown@example.com"},
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert "message" in known.json()
    # Token state is not corrupted by the delivery failure.
    from sqlalchemy import select

    from app.models.password_reset_token import PasswordResetToken

    rows = (
        await async_db.execute(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id),
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_fake_delivery_link_completes_reset(
    _clean_mailer_state: None,
    client: AsyncClient,
    async_db,
) -> None:
    """The delivered fake link carries the one-time token that resets."""
    fake = FakePasswordResetMailer()
    override_password_reset_mailer(fake)
    user = await get_user_by_username(async_db, "maillinkuser")
    if user is None:
        user = await create_user(
            async_db,
            username="maillinkuser",
            email="maillink@example.com",
            password_hash=hash_password("oldpw"),
        )
        await async_db.commit()
    response = await client.post(
        "/api/auth/forgot-password",
        json={"email": "maillink@example.com"},
    )
    assert response.status_code == 200
    assert len(fake.sent) == 1
    delivered_token = urllib.parse.parse_qs(
        urllib.parse.urlparse(fake.sent[0].reset_url).query,
    )["token"][0]
    assert await complete_reset(async_db, delivered_token, "brand-new-pw") is True
