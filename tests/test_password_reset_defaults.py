"""Password-reset delivery defaults should require only the Resend secret."""

import pytest

from app.config import clear_settings_cache
from app.services.password_reset_mailer import (
    NON_PRODUCTION_RESET_ORIGIN,
    NON_PRODUCTION_RESET_SENDER,
    PRODUCTION_RESET_ORIGIN,
    PRODUCTION_RESET_SENDER,
    ResendPasswordResetMailer,
    get_password_reset_mailer,
    override_password_reset_mailer,
)


@pytest.fixture(autouse=True)
def _clean_email_config(monkeypatch: pytest.MonkeyPatch):
    """Keep environment-driven mailer resolution isolated between tests."""
    for var in (
        "RESEND_API_KEY",
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


def test_production_needs_only_resend_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production uses ComicPile defaults when only the Resend secret is set."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RESEND_API_KEY", "re_live_key")
    clear_settings_cache()

    mailer = get_password_reset_mailer()

    assert isinstance(mailer, ResendPasswordResetMailer)
    assert mailer.api_key == "re_live_key"
    assert mailer.sender == PRODUCTION_RESET_SENDER
    assert mailer.origin == PRODUCTION_RESET_ORIGIN


def test_non_production_uses_harmless_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-production defaults never point reset links at production."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    clear_settings_cache()

    mailer = get_password_reset_mailer()

    assert isinstance(mailer, ResendPasswordResetMailer)
    assert mailer.sender == NON_PRODUCTION_RESET_SENDER
    assert mailer.origin == NON_PRODUCTION_RESET_ORIGIN


def test_explicit_sender_and_origin_still_override_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Self-hosters and tests may still replace the built-in defaults."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RESEND_API_KEY", "re_live_key")
    monkeypatch.setenv("PASSWORD_RESET_SENDER", "Custom <mail@example.com>")
    monkeypatch.setenv("PASSWORD_RESET_ORIGIN", "https://custom.example.com")
    clear_settings_cache()

    mailer = get_password_reset_mailer()

    assert isinstance(mailer, ResendPasswordResetMailer)
    assert mailer.sender == "Custom <mail@example.com>"
    assert mailer.origin == "https://custom.example.com"
