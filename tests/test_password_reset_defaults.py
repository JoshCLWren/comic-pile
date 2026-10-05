"""Password-reset delivery defaults for Gmail SMTP."""

import pytest

from app.config import clear_settings_cache
from app.services.password_reset_mailer import (
    GmailPasswordResetMailer,
    NON_PRODUCTION_RESET_ORIGIN,
    PRODUCTION_RESET_ORIGIN,
    get_password_reset_mailer,
    override_password_reset_mailer,
)


@pytest.fixture(autouse=True)
def _clean_email_config(monkeypatch: pytest.MonkeyPatch):
    """Keep environment-driven mailer resolution isolated between tests."""
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
    yield
    override_password_reset_mailer(None)
    clear_settings_cache()


def test_production_needs_only_gmail_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production uses the Gmail identity and ComicPile origin by default."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("GMAIL_SMTP_USERNAME", "owner@gmail.com")
    monkeypatch.setenv("GMAIL_SMTP_APP_PASSWORD", "app-password")
    clear_settings_cache()

    mailer = get_password_reset_mailer()

    assert isinstance(mailer, GmailPasswordResetMailer)
    assert mailer.username == "owner@gmail.com"
    assert mailer.app_password == "app-password"
    assert mailer.sender == "Comic Pile <owner@gmail.com>"
    assert mailer.origin == PRODUCTION_RESET_ORIGIN


def test_non_production_uses_local_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-production reset links never point at production by default."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("GMAIL_SMTP_USERNAME", "owner@gmail.com")
    monkeypatch.setenv("GMAIL_SMTP_APP_PASSWORD", "app-password")
    clear_settings_cache()

    mailer = get_password_reset_mailer()

    assert isinstance(mailer, GmailPasswordResetMailer)
    assert mailer.sender == "Comic Pile <owner@gmail.com>"
    assert mailer.origin == NON_PRODUCTION_RESET_ORIGIN


def test_explicit_sender_and_origin_still_override_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured Gmail alias and custom public origin may override defaults."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("GMAIL_SMTP_USERNAME", "owner@gmail.com")
    monkeypatch.setenv("GMAIL_SMTP_APP_PASSWORD", "app-password")
    monkeypatch.setenv("PASSWORD_RESET_SENDER", "Comic Pile <alias@gmail.com>")
    monkeypatch.setenv("PASSWORD_RESET_ORIGIN", "https://custom.example.com")
    clear_settings_cache()

    mailer = get_password_reset_mailer()

    assert isinstance(mailer, GmailPasswordResetMailer)
    assert mailer.sender == "Comic Pile <alias@gmail.com>"
    assert mailer.origin == "https://custom.example.com"
