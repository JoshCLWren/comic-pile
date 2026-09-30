"""Cache provider regression tests.

These cover the retained cache implementation itself: circuit breaking, TTL
handling, value type preservation, reconnect behavior, and the transactional
guarantee that a blocked-status refresh never populates the cache.

Endpoint read-after-write behavior for the de-cached read paths lives in
``tests/test_read_path_without_cache_provider.py`` (issue #2972).
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache


@pytest_asyncio.fixture(autouse=True)
async def _reinitialize_cache() -> AsyncIterator[None]:
    """Reinitialize cache in current event loop to avoid cross-loop issues."""
    from app.config import get_redis_settings

    if cache.is_initialized:
        try:
            await cache.close()
        except RuntimeError:
            cache._client = None
            cache._initialized = False
    settings = get_redis_settings()
    if not settings.redis_url:
        assert settings.redis_url is not None, "REDIS_URL is required for cache regression tests"
    await cache.initialize(local_url=settings.redis_url, allow_local=True)
    assert cache.is_initialized, "Cache failed to initialize for cache regression tests"
    yield


@pytest.mark.asyncio
async def test_cache_circuit_breaker_resets_on_success(
    async_db: AsyncSession,
) -> None:
    """Verify the circuit breaker resets failure count on closed-state success."""
    from app.cache import CircuitBreaker

    cb = CircuitBreaker(name="test", failure_threshold=3, reset_timeout_seconds=1)

    cb.record_failure()
    cb.record_failure()
    assert cb._state.value == "closed"
    assert cb._failure_count == 2

    cb.record_success()
    assert cb._failure_count == 0, (
        f"Expected failure_count=0 after success, got {cb._failure_count}"
    )


@pytest.mark.asyncio
async def test_cache_falsy_ttl_caches_empty_result(
    async_db: AsyncSession,
) -> None:
    """Verify falsy_ttl caches falsy results (empty list) instead of skipping them."""
    await cache.clear_pattern("cache:*")

    cached_val = await cache.get("cache:test_falsy:never_set:")
    assert cached_val is None

    assert await cache.set("cache:test_falsy:empty_list:", [], ttl=30)
    result = await cache.get("cache:test_falsy:empty_list:")
    assert result is not None, "Empty list should be cacheable with falsy_ttl"
    assert result == []

    assert await cache.set("cache:test_falsy:zero:", 0, ttl=30)
    result = await cache.get("cache:test_falsy:zero:")
    assert result is not None, "Zero should be cacheable with falsy_ttl"
    assert result == 0


@pytest.mark.asyncio
async def test_cache_set_type_preservation(
    async_db: AsyncSession,
) -> None:
    """Verify that cached sets are returned as sets, not lists."""
    await cache.clear_pattern("cache:*")

    test_set = {1, 2, 3}
    assert await cache.set("cache:test_set_preservation:", test_set, ttl=30)
    result = await cache.get("cache:test_set_preservation:")
    assert isinstance(result, set), f"Expected set, got {type(result)}"
    assert result == {1, 2, 3}

    test_dict = {"a": {1, 2}, "b": {3, 4}}
    assert await cache.set("cache:test_nested_set:", test_dict, ttl=30)
    result = await cache.get("cache:test_nested_set:")
    assert isinstance(result, dict)
    assert isinstance(result["a"], set)
    assert isinstance(result["b"], set)
    assert result["a"] == {1, 2}
    assert result["b"] == {3, 4}


@pytest.mark.asyncio
async def test_cache_reinitialize_resets_open_circuit() -> None:
    """A successful reconnect closes an earlier open circuit."""
    from app.cache import CircuitState
    from app.config import get_redis_settings

    settings = get_redis_settings()
    assert settings.redis_url is not None

    # Access the backend's circuit breaker
    backend = cache._backend
    assert backend is not None, "Cache backend not initialized"
    for _ in range(backend._circuit_breaker.failure_threshold):
        backend._circuit_breaker.record_failure()
    assert backend._circuit_breaker.state == CircuitState.OPEN

    await cache.close()
    await cache.initialize(local_url=settings.redis_url, allow_local=True)

    assert cache.is_initialized
    # After reinitialize, we have a new backend
    new_backend = cache._backend
    assert new_backend is not None
    assert new_backend._circuit_breaker.state == CircuitState.CLOSED
    assert await cache.set("cache:test_reconnect:", "healthy", ttl=30)
    assert await cache.get("cache:test_reconnect:") == "healthy"


@pytest.mark.asyncio
async def test_cache_zero_ttl_does_not_persist() -> None:
    """An explicit zero TTL removes the key instead of caching forever."""
    key = "cache:test_zero_ttl:"
    assert await cache.set(key, "value", ttl=30)
    assert await cache.get(key) == "value"

    assert await cache.set(key, "replacement", ttl=0)
    assert await cache.get(key) is None


@pytest.mark.asyncio
async def test_refresh_blocked_status_uses_the_uncached_blocked_thread_read(
    async_db: AsyncSession,
    sample_data: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The transactional refresh must never use the non-transactional read.

    ``get_blocked_thread_ids`` shares the uncached evaluator, but the refresh
    path must stay on ``_get_blocked_thread_ids_uncached`` so it reads inside
    the caller's transaction rather than through a second connection.
    """
    import comic_pile.dependencies as dependencies_module

    user = sample_data["user"]

    async def fail_if_non_transactional_read_is_used(
        user_id: int, db: AsyncSession
    ) -> set[int]:
        raise AssertionError(f"non-transactional blocked-thread read used for user {user_id}")

    monkeypatch.setattr(
        dependencies_module,
        "get_blocked_thread_ids",
        fail_if_non_transactional_read_is_used,
    )

    await dependencies_module.refresh_user_blocked_status(user.id, async_db)
    await async_db.rollback()
