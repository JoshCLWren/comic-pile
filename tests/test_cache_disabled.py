"""Test that application functions correctly with Redis caching disabled."""

import pytest
from httpx import AsyncClient

from app.config import get_redis_settings


@pytest.mark.asyncio
async def test_app_works_with_cache_disabled(auth_client: AsyncClient) -> None:
    """Test that core application functions work when Redis is disabled."""
    # Verify cache is disabled in test configuration
    redis_settings = get_redis_settings()
    assert redis_settings.effective_provider == "off", "Cache should be disabled for this test"
    
    # Test that ping endpoint works (no cache dependency)
    response = await auth_client.get("/api/ping")
    assert response.status_code == 200
    assert "pong" in response.json()["message"]
    
    # Test that health endpoint works (no cache dependency)
    response = await auth_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["database"] == "connected"


@pytest.mark.asyncio
async def test_cache_operations_noop_when_disabled(auth_client: AsyncClient) -> None:
    """Test that cache operations are no-ops when caching is disabled."""
    # Verify cache is disabled
    redis_settings = get_redis_settings()
    assert redis_settings.effective_provider == "off"
    
    # Test that cache invalidation is a no-op when disabled
    # This should not raise an exception even though cache is disabled
    from app.cache import invalidate_cache
    
    # This should return 0 (no keys deleted) when cache is disabled
    result = await invalidate_cache("test:*")
    assert result == 0


@pytest.mark.asyncio
async def test_cached_decorator_works_without_cache(auth_client: AsyncClient) -> None:
    """Test that @cached decorator functions correctly when cache is disabled."""
    from app.cache import cached, TTL
    
    @cached(ttl=TTL.SHORT)
    async def test_cached_function(user_id: int) -> dict:
        """Test function that should work with or without cache."""
        return {"user_id": user_id, "data": "test_value"}
    
    # Test that the function works normally even when cache is disabled
    result1 = await test_cached_function(1)
    result2 = await test_cached_function(1)
    
    # Both calls should return the same result (function is deterministic)
    assert result1 == result2
    assert result1["user_id"] == 1
    assert result1["data"] == "test_value"


@pytest.mark.asyncio
async def test_app_functionality_without_cache_dependency(
    auth_client: AsyncClient, sample_data: None
) -> None:
    """Test that core app functionality works without cache dependencies."""
    # Test Roll bootstrap (should work without cache)
    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200
    
    # Test Queue load (should work without cache)
    response = await auth_client.get("/api/queue")
    assert response.status_code == 200
    
    # Test thread operations (should work without cache)
    response = await auth_client.get("/api/threads")
    assert response.status_code == 200
    
    # Test auth endpoints (should work without cache)
    response = await auth_client.get("/api/auth/me")
    assert response.status_code == 200