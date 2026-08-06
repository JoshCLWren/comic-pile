"""Regression tests for the explicit Redis cache feature gate."""

from app.config import RedisSettings


def test_cache_defaults_to_disabled_with_remote_credentials_present() -> None:
    """Credentials alone must not make deployed caching active."""
    settings = RedisSettings(
        _env_file=None,
        upstash_redis_rest_url="https://example.upstash.io",
        upstash_redis_rest_token="test-token",
    )

    assert settings.cache_enabled is False
    assert settings.is_configured is False


def test_preview_style_redis_url_defaults_to_disabled() -> None:
    """A preview environment cannot contact Redis without an explicit opt-in."""
    settings = RedisSettings(
        _env_file=None,
        redis_url="rediss://default:test-token@example.upstash.io:6379/0",
    )

    assert settings.is_configured is False


def test_local_cache_configuration_requires_explicit_enablement() -> None:
    """Disposable local Redis remains available when tests opt in."""
    settings = RedisSettings(
        _env_file=None,
        cache_enabled=True,
        redis_url="redis://localhost:6379/0",
    )

    assert settings.is_configured is True


def test_incomplete_upstash_configuration_stays_disabled() -> None:
    """The feature gate cannot activate a partially configured remote cache."""
    settings = RedisSettings(
        _env_file=None,
        cache_enabled=True,
        upstash_redis_rest_url="https://example.upstash.io",
    )

    assert settings.is_configured is False
