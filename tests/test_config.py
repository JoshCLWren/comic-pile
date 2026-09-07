"""Configuration default and environment override tests."""

import pytest

from app.config import RedisSettings, RecommendationSettings


def test_redis_cache_ttl_defaults_reduce_churn_for_reenable_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use longer cache tiers by default to reduce repeated database work.

    The tuned tiers (2:6:15 minutes) cut cache-command churn versus the original
    30/60/120 defaults while generation invalidation keeps user data fresh.

    Args:
        monkeypatch: Pytest fixture used to remove cache TTL environment overrides.

    Returns:
        None.
    """
    monkeypatch.delenv("CACHE_TTL_SHORT", raising=False)
    monkeypatch.delenv("CACHE_TTL_MEDIUM", raising=False)
    monkeypatch.delenv("CACHE_TTL_LONG", raising=False)

    settings = RedisSettings()

    assert settings.cache_ttl_short == 120
    assert settings.cache_ttl_medium == 360
    assert settings.cache_ttl_long == 900


def test_redis_cache_ttl_environment_overrides_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep deployment-specific TTL values authoritative over the defaults.

    Args:
        monkeypatch: Pytest fixture used to set cache TTL environment overrides.

    Returns:
        None.
    """
    monkeypatch.setenv("CACHE_TTL_SHORT", "15")
    monkeypatch.setenv("CACHE_TTL_MEDIUM", "45")
    monkeypatch.setenv("CACHE_TTL_LONG", "90")

    settings = RedisSettings()

    assert settings.cache_ttl_short == 15
    assert settings.cache_ttl_medium == 45
    assert settings.cache_ttl_long == 90


def test_recommendation_control_mode_env_kill_switch_is_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Honor RECOMMENDATION_CONTROL_MODE as the operator kill switch.

    pydantic-settings v2 silently ignores ``json_schema_extra`` env names, so the
    documented operator variable must be wired through ``validation_alias``.
    Without this the legacy control mode could never be reached from the
    environment and contextual selection could not be disabled.

    Args:
        monkeypatch: Pytest fixture used to set recommendation env overrides.

    Returns:
        None.
    """
    monkeypatch.delenv("RECOMMENDATION_CONTROL_MODE", raising=False)
    monkeypatch.delenv("CONTROL_MODE", raising=False)
    monkeypatch.delenv("RECOMMENDATION_ALGORITHM_VERSION", raising=False)
    monkeypatch.delenv("ALGORITHM_VERSION", raising=False)

    assert RecommendationSettings().control_mode == "contextual"

    monkeypatch.setenv("RECOMMENDATION_CONTROL_MODE", "legacy")
    assert RecommendationSettings().control_mode == "legacy"
