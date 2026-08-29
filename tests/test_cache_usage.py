"""Tests for the one-command cache usage report vs budget."""

from __future__ import annotations

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
