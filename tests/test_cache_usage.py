"""Tests for the one-command cache usage report vs budget."""

from __future__ import annotations

import pytest

from app.cache_usage import build_cache_usage_report, format_cache_usage_report


def test_report_ok_within_budget() -> None:
    """Observed usage under the alert band reports ok with the right headroom."""
    report = build_cache_usage_report(observed_commands=1000)

    assert report.status == "ok"
    assert report.observed_ratio == 1000 / 350_000
    assert report.headroom_remaining == 349_000
    assert report.application_budget == 350_000
    assert "Within budget" in report.recommendation


def test_report_near_limit_at_alert_band() -> None:
    """Crossing 80% of the budget flips to near-limit with a guardrail note."""
    report = build_cache_usage_report(observed_commands=280_000)

    assert report.status == "near-limit"
    assert report.recommendation.startswith("Approaching")


def test_report_over_budget_recommends_disable() -> None:
    """Reaching the hard budget recommends disabling CACHE_ENABLED."""
    report = build_cache_usage_report(observed_commands=350_000)

    assert report.status == "over-budget"
    assert "Disable CACHE_ENABLED" in report.recommendation


def test_report_accepts_provider_commands() -> None:
    """An operator-supplied provider count populates the provider ratio."""
    report = build_cache_usage_report(
        observed_commands=1000,
        provider_commands=120_000,
    )

    assert report.provider_commands == 120_000
    assert report.provider_ratio == 120_000 / 500_000


def test_report_rejects_negative_usage() -> None:
    """Negative observed or provider counts are rejected as invalid evidence."""
    import pytest

    with pytest.raises(ValueError):
        build_cache_usage_report(observed_commands=-1)
    with pytest.raises(ValueError):
        build_cache_usage_report(provider_commands=-1)


def test_resolve_provider_commands_prefers_explicit_count() -> None:
    """An operator-supplied figure wins over live Upstash credentials."""
    from scripts.cache_usage_report import resolve_provider_commands

    assert resolve_provider_commands(14500) == 14500


def test_resolve_provider_commands_fetches_upstash_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make cache-usage includes provider month-to-date when management creds exist."""
    from scripts import cache_usage_report as usage_cli

    monkeypatch.setenv("UPSTASH_EMAIL", "ops@example.com")
    monkeypatch.setenv("UPSTASH_API_KEY", "test-key")

    class _Live:
        used_commands = 1234

    def _fake_build(**kwargs: object) -> _Live:
        assert kwargs["email"] == "ops@example.com"
        assert kwargs["api_key"] == "test-key"
        return _Live()

    monkeypatch.setattr(
        "app.cache_usage_report.build_cache_usage_report",
        _fake_build,
    )

    assert usage_cli.resolve_provider_commands(None) == 1234


def test_resolve_provider_commands_skips_without_management_creds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing Upstash management credentials leave provider commands unset."""
    from scripts.cache_usage_report import resolve_provider_commands

    monkeypatch.delenv("UPSTASH_EMAIL", raising=False)
    monkeypatch.delenv("UPSTASH_API_KEY", raising=False)

    assert resolve_provider_commands(None) is None


def test_report_serializes_to_dict_and_text() -> None:
    """Both the dict and text renderers produce expected keys/lines."""
    report = build_cache_usage_report(observed_commands=5000)

    assert set(report.as_dict()) >= {
        "observed_commands",
        "application_budget",
        "status",
        "recommendation",
    }
    text = format_cache_usage_report(report)
    assert "ComicPile cache usage vs Upstash budget" in text
    assert "Status" in text
