"""Password-reset delivery defaults should require only the Resend secret."""

import pytest

from app.config import clear_settings_cache, get_email_settings
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
    assert mailer.path == "/reset-password"
    assert get_email_settings().is_configured


def test_non_production_uses_harmless_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-production defaults never point reset links at production."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    clear_settings_cache()

    mailer = get_password_reset_mailer()

    assert isinstance(mailer, ResendPasswordResetMailer)
    assert mailer.sender == NON_PRODUCTION_RESET_SENDER
    assert mailer.origin == NON_PRODUCTION_RESET_ORIGIN


@pytest.mark.parametrize("environment", ["production", "development"])
def test_overrides_apply_only_outside_production(
    environment: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale deployment overrides cannot change production sender or reset links."""
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("RESEND_API_KEY", " \r\nre_live_key\n ")
    monkeypatch.setenv("PASSWORD_RESET_SENDER", "Custom <mail@example.com>")
    monkeypatch.setenv("PASSWORD_RESET_ORIGIN", "https://custom.example.com")
    monkeypatch.setenv("PASSWORD_RESET_PATH", "stale-reset")
    clear_settings_cache()

    mailer = get_password_reset_mailer()

    assert isinstance(mailer, ResendPasswordResetMailer)
    assert mailer.api_key == "re_live_key"
    if environment == "production":
        assert mailer.sender == PRODUCTION_RESET_SENDER
        assert mailer.origin == PRODUCTION_RESET_ORIGIN
        assert mailer.path == "/reset-password"
    else:
        assert mailer.sender == "Custom <mail@example.com>"
        assert mailer.origin == "https://custom.example.com"
        assert mailer.path == "/stale-reset"
