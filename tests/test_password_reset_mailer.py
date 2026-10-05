"""Focused acceptance tests for #2778 password-reset email delivery."""

import hashlib
import logging
import smtplib
import urllib.parse
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import cast

import pytest
from httpx import AsyncClient
from starlette.background import BackgroundTasks

from app.auth import hash_password
from app.config import clear_settings_cache, get_email_settings
from app.repositories.user_repository import create_user, get_user_by_username
from app.services.password_reset_mailer import (
    FakePasswordResetMailer,
    GmailPasswordResetMailer,
    PasswordResetDeliveryError,
    build_password_reset_text_body,
    build_password_reset_url,
    get_fake_mailer,
    get_password_reset_mailer,
    override_password_reset_mailer,
)
from app.services.password_reset_service import (
    TOKEN_EXPIRY_MINUTES,
    complete_reset,
    handle_forgot_password_request,
    request_forgot_password,
)


@pytest.fixture
def _clean_mailer_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate mailer singletons and email settings between tests."""
    for var in (
        "GMAIL_SMTP_USERNAME",
        "GMAIL_SMTP_APP_PASSWORD",
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
async def test_gmail_adapter_sends_message_without_logging_token(
    _clean_mailer_state: None,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gmail SMTP uses configured identity and never logs the reset token."""
    captured: dict[str, object] = {}

    class _FakeSMTP:
        def __init__(
            self,
            host: str,
            port: int,
            *,
            timeout: float,
            context: object,
        ) -> None:
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout

        def __enter__(self) -> "_FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            captured["username"] = username
            captured["password"] = password

        def send_message(self, message: object) -> None:
            captured["message"] = message

    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
    raw_token = "super-secret-raw-token"
    mailer = GmailPasswordResetMailer(
        username="owner@gmail.com",
        app_password="app-password",
        sender="Comic Pile <owner@gmail.com>",
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

    message = cast(EmailMessage, captured["message"])
    assert message["From"] == "Comic Pile <owner@gmail.com>"
    assert message["To"] == "user@example.com"
    assert message["Subject"]
    body = message.get_content()
    assert f"{TOKEN_EXPIRY_MINUTES} minutes" in body
    assert body.count(raw_token) == 1
    assert captured["username"] == "owner@gmail.com"
    assert captured["password"] == "app-password"
    for record in caplog.records:
        assert raw_token not in record.getMessage()
        assert raw_token not in str(record.args)


@pytest.mark.asyncio
async def test_gmail_provider_failure_raises_without_token_in_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SMTP failures surface as delivery errors without leaking the reset token."""

    class _FailingSMTP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_FailingSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

        def send_message(self, message: object) -> None:
            raise AssertionError("send_message must not run after auth failure")

    monkeypatch.setattr(smtplib, "SMTP_SSL", _FailingSMTP)
    mailer = GmailPasswordResetMailer(
        username="owner@gmail.com",
        app_password="bad-password",
        sender="Comic Pile <owner@gmail.com>",
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


def test_mailer_resolution_prefers_gmail_when_configured_else_fake(
    _clean_mailer_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured Gmail settings resolve SMTP; otherwise use the deterministic fake."""
    assert isinstance(get_password_reset_mailer(), FakePasswordResetMailer)
    monkeypatch.setenv("GMAIL_SMTP_USERNAME", "owner@gmail.com")
    monkeypatch.setenv("GMAIL_SMTP_APP_PASSWORD", "app-password")
    monkeypatch.setenv("PASSWORD_RESET_SENDER", "Comic Pile <owner@gmail.com>")
    monkeypatch.setenv("PASSWORD_RESET_ORIGIN", "https://app.example.com")
    clear_settings_cache()
    mailer = get_password_reset_mailer()
    assert isinstance(mailer, GmailPasswordResetMailer)
    assert mailer.sender == "Comic Pile <owner@gmail.com>"
    assert mailer.origin == "https://app.example.com"
    assert mailer.username == "owner@gmail.com"
    assert mailer.app_password == "app-password"


def test_placeholder_gmail_secret_counts_as_unconfigured(
    _clean_mailer_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Placeholder Gmail secrets never activate the production adapter."""
    monkeypatch.setenv("GMAIL_SMTP_USERNAME", "owner@gmail.com")
    monkeypatch.setenv("GMAIL_SMTP_APP_PASSWORD", "redacted")
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


@pytest.mark.asyncio
async def test_delivery_is_deferred_to_background_task(
    _clean_mailer_state: None,
    async_db,
) -> None:
    """The service only schedules delivery, keeping the ack path provider-free."""
    if await get_user_by_username(async_db, "bgdeferuser") is None:
        await create_user(
            async_db,
            username="bgdeferuser",
            email="bgdefer@example.com",
            password_hash=hash_password("pw"),
        )
        await async_db.commit()

    tasks = BackgroundTasks()
    await handle_forgot_password_request(async_db, "bgdefer@example.com", tasks)

    # Nothing has touched the mailer yet: provider latency cannot leak
    # account existence through response timing.
    assert len(tasks.tasks) == 1
    assert len(get_fake_mailer().sent) == 0

    await tasks()
    assert len(get_fake_mailer().sent) == 1
    assert get_fake_mailer().sent[0].recipient_email == "bgdefer@example.com"
