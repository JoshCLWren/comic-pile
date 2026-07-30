"""Configuration default and environment override tests."""

import pytest

from app.config import RedisSettings


def test_redis_cache_ttl_defaults_are_three_times_the_original_values() -> None:
    """Use longer cache tiers by default to reduce repeated database work."""
    settings = RedisSettings(_env_file=None)

    assert settings.cache_ttl_short == 90
    assert settings.cache_ttl_medium == 180
    assert settings.cache_ttl_long == 360


def test_redis_cache_ttl_environment_overrides_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep deployment-specific TTL values authoritative over the defaults."""
    monkeypatch.setenv("CACHE_TTL_SHORT", "15")
    monkeypatch.setenv("CACHE_TTL_MEDIUM", "45")
    monkeypatch.setenv("CACHE_TTL_LONG", "90")

    settings = RedisSettings(_env_file=None)

    assert settings.cache_ttl_short == 15
    assert settings.cache_ttl_medium == 45
    assert settings.cache_ttl_long == 90
