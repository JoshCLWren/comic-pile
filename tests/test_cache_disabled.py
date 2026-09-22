"""Test that application functions correctly with Redis caching disabled."""

import pytest
from httpx import AsyncClient

from app.config import RedisSettings, clear_settings_cache


def _make_off_settings(**overrides: object) -> RedisSettings:
    """Build RedisSettings with cache_provider=off for disabled-cache tests."""
    values: dict[str, object] = {
        "cache_provider": "off",
        "cache_enabled": False,
        "upstash_redis_rest_url": None,
        "upstash_redis_rest_token": None,
        "redis_url": None,
    }
    values.update(overrides)
    return RedisSettings.model_validate(values)


@pytest.mark.asyncio
async def test_app_works_with_cache_disabled(auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that core application functions work when Redis is disabled."""
    monkeypatch.setenv("CACHE_PROVIDER", "off")
    monkeypatch.setenv("CACHE_ENABLED", "false")
    clear_settings_cache()

    redis_settings = _make_off_settings()
    assert redis_settings.effective_provider == "off", "Cache should be disabled for this test"

    response = await auth_client.get("/api/ping")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"

    response = await auth_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_cache_operations_noop_when_disabled(auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that cache operations are no-ops when caching is disabled."""
    monkeypatch.setenv("CACHE_PROVIDER", "off")
    monkeypatch.setenv("CACHE_ENABLED", "false")
    clear_settings_cache()

    redis_settings = _make_off_settings()
    assert redis_settings.effective_provider == "off"

    from app.cache import invalidate_cache

    result = await invalidate_cache("test:*")
    assert result == 0


@pytest.mark.asyncio
async def test_cached_decorator_works_without_cache(auth_client: AsyncClient) -> None:
    """Test that @cached decorator functions correctly when cache is disabled."""
    from app.cache import TTL, cached

    @cached(ttl=TTL.SHORT)
    async def test_cached_function(user_id: int) -> dict:
        """Test function that should work with or without cache."""
        return {"user_id": user_id, "data": "test_value"}

    result1 = await test_cached_function(1)
    result2 = await test_cached_function(1)

    assert result1 == result2
    assert result1["user_id"] == 1
    assert result1["data"] == "test_value"


@pytest.mark.asyncio
async def test_app_functionality_without_cache_dependency(
    auth_client: AsyncClient, sample_data: None
) -> None:
    """Test that core app functionality works without cache dependencies."""
    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200

    response = await auth_client.get("/api/threads/")
    assert response.status_code == 200

    response = await auth_client.get("/api/auth/me")
    assert response.status_code == 200
