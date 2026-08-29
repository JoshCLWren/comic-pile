"""Cache wrapper tests run against both cache backends (Redis + Postgres).

Implements the #1781 acceptance contract: the operations the Upstash client
exposes (get/set/delete, generation bump/read, incr, fail-open) must behave
identically behind the shared ``CacheRouter`` interface for both the Redis
transport (``UpstashCache``) and the Postgres transport (``PostgresCache``).

The tests are parametrized over both backends so a regression in either client
fails the suite. When a backend is not configured in the test environment its
variant is skipped (CI provisions both Redis and PostgreSQL).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from app.cache import TTL, CacheRouter, cached, cache


def _redis_url() -> str | None:
    """Return the configured local Redis URL, or ``None`` when absent."""
    from app.config import get_redis_settings

    return get_redis_settings().redis_url


def _postgres_test_url() -> str | None:
    """Return a PostgreSQL test database URL, or ``None`` when absent."""
    url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if url and url.startswith("postgresql"):
        return url
    return None


@pytest.fixture(params=["redis", "postgres"], ids=["redis", "postgres"])
async def cache_router(
    request: pytest.FixtureRequest,
    db_engine: object,
) -> AsyncIterator[CacheRouter]:
    """Provide a ``CacheRouter`` configured against one real backend per param.

    Args:
        request: Pytest request carrying the backend param (``redis``/``postgres``).
        db_engine: Session-scoped engine fixture ensuring the schema (incl. cache
            tables) exists before the Postgres backend is initialized.

    Yields:
        A configured :class:`CacheRouter` using the selected backend.
    """
    del db_engine  # only needed for its schema side effect
    kind = request.param
    router = CacheRouter()
    try:
        if kind == "redis":
            redis_url = _redis_url()
            if not redis_url:
                pytest.skip("REDIS_URL not configured; skipping Redis backend variant")
            await router.configure("redis", local_url=redis_url)
        else:
            db_url = _postgres_test_url()
            if not db_url:
                pytest.skip(
                    "PostgreSQL test database not configured; skipping Postgres backend variant"
                )
            await router.configure("postgres", database_url=db_url)
            await router.clear_pattern("cache:*")
        assert router.is_initialized
        yield router
    finally:
        await router.close()


# --- Backend-agnostic wrapper contract ---------------------------------------


@pytest.mark.asyncio
async def test_set_then_get_roundtrip(cache_router: CacheRouter) -> None:
    """A value stored under a key is returned byte-for-byte on read."""
    key = "cache:wrapper:setget:"
    assert await cache_router.set(key, {"hello": "world", "n": 3}, ttl=30)
    assert await cache_router.get(key) == {"hello": "world", "n": 3}


@pytest.mark.asyncio
async def test_set_preserves_nested_container_types(cache_router: CacheRouter) -> None:
    """Sets and nested sets survive JSON round-tripping on either backend."""
    key = "cache:wrapper:nested:"
    payload = {"a": {1, 2}, "b": {3, 4}, "c": [5, 6]}
    assert await cache_router.set(key, payload, ttl=30)
    got = await cache_router.get(key)
    assert isinstance(got, dict)
    assert isinstance(got["a"], set)
    assert isinstance(got["b"], set)
    assert got["a"] == {1, 2}
    assert got["b"] == {3, 4}
    assert got["c"] == [5, 6]


@pytest.mark.asyncio
async def test_delete_removes_existing_key(cache_router: CacheRouter) -> None:
    """Deleting a present key makes the next read a miss."""
    key = "cache:wrapper:delete:"
    await cache_router.set(key, "value", ttl=30)
    assert await cache_router.get(key) == "value"
    assert isinstance(await cache_router.delete(key), bool)
    assert await cache_router.get(key) is None


@pytest.mark.asyncio
async def test_clear_pattern_is_scoped(cache_router: CacheRouter) -> None:
    """clear_pattern removes only keys matching the glob, counting deletions."""
    await cache_router.set("cache:wrapper:cp:one:", "a", ttl=30)
    await cache_router.set("cache:wrapper:cp:two:", "b", ttl=30)
    await cache_router.set("cache:wrapper:keep:", "c", ttl=30)
    deleted = await cache_router.clear_pattern("cache:wrapper:cp:*")
    assert deleted == 2
    assert await cache_router.get("cache:wrapper:cp:one:") is None
    assert await cache_router.get("cache:wrapper:cp:two:") is None
    assert await cache_router.get("cache:wrapper:keep:") == "c"


@pytest.mark.asyncio
async def test_zero_ttl_does_not_persist(cache_router: CacheRouter) -> None:
    """An explicit zero TTL removes the key instead of caching it forever."""
    key = "cache:wrapper:zero:"
    assert await cache_router.set(key, "value", ttl=30)
    assert await cache_router.get(key) == "value"
    assert await cache_router.set(key, "replacement", ttl=0)
    assert await cache_router.get(key) is None


@pytest.mark.asyncio
async def test_generation_incr_and_read(cache_router: CacheRouter) -> None:
    """The generation bump increments monotonically and reads back the value."""
    import uuid

    scope = f"wrapper:gen:{uuid.uuid4()}"
    assert await cache_router.get_generation(scope) == 0
    assert await cache_router.incr(scope) == 1
    assert await cache_router.incr(scope) == 2
    assert await cache_router.get_generation(scope) == 2


@pytest.mark.asyncio
async def test_decode_value_roundtrip(cache_router: CacheRouter) -> None:
    """decode_value reconstructs JSON text from either backend codec."""
    decoded = cache_router.decode_value('{"a": [1, 2, 3], "flag": true}')
    assert decoded == {"a": [1, 2, 3], "flag": True}


@pytest.mark.asyncio
async def test_atomic_generation_read_postgres(cache_router: CacheRouter) -> None:
    """The Postgres atomic generation+value read mirrors the Redis Lua path."""
    import json
    import uuid

    if cache_router.provider_kind != "postgres":
        pytest.skip("atomic_generation_read is Postgres-specific")
    generation_key = f"wrapper:agen:{uuid.uuid4()}"
    value_key = f"cache:user:1:g1:wrapper:avalue:"
    await cache_router.incr(generation_key)
    assert await cache_router.set(value_key, {"x": 1}, ttl=30)
    raw = await cache_router.atomic_generation_read(
        generation_key, "cache:user:1:g", "wrapper:avalue:"
    )
    assert raw[0] == 1
    assert json.loads(raw[1]) == {"x": 1}


# --- Fail-open behavior (must be preserved across both backends) --------------


@pytest.mark.asyncio
async def test_fail_open_when_uninitialized() -> None:
    """An unconfigured router never raises and returns safe default values."""
    router = CacheRouter()
    assert router.is_initialized is False
    assert await router.get("cache:x:") is None
    assert await router.set("cache:x:", "v") is False
    assert await router.delete("cache:x:") is False
    assert await router.clear_pattern("cache:x:*") == 0
    assert await router.get_generation("cache:x:") == 0


@pytest.mark.asyncio
async def test_fail_open_after_demote() -> None:
    """Once demoted, the router stays fail-open for the process lifetime."""
    redis_url = _redis_url()
    db_url = _postgres_test_url()
    router = CacheRouter()
    if db_url:
        await router.configure("postgres", database_url=db_url)
    elif redis_url:
        await router.configure("redis", local_url=redis_url)
    else:
        pytest.skip("No cache backend available to exercise demotion")
    assert router.is_initialized
    await router.demote()
    assert router.is_initialized is False
    assert await router.get("cache:x:") is None
    assert await router.set("cache:x:", "v") is False
    assert await router.delete("cache:x:") is False
    assert await router.clear_pattern("cache:x:*") == 0


# --- The ``cached`` wrapper must behave identically on both clients -----------


@pytest.fixture(params=["redis", "postgres"], ids=["redis", "postgres"])
async def wrapper_cache(request: pytest.FixtureRequest, db_engine: object) -> AsyncIterator[str]:
    """Reconfigure the module-global ``cache`` router to one backend per param.

    The :func:`app.cache.cached` decorator binds to the process-wide ``cache``
    singleton, so exercising it against a backend requires reconfiguring that
    singleton and restoring it afterwards to avoid leaking state into other tests.

    Args:
        request: Pytest request carrying the backend param.
        db_engine: Ensures schema exists before the Postgres backend initializes.

    Yields:
        The selected backend kind (``"redis"`` or ``"postgres"``).
    """
    del db_engine
    kind = request.param
    prior_initialized = cache.is_initialized
    prior_kind = cache.provider_kind
    if cache.is_initialized:
        try:
            await cache.close()
        except RuntimeError:
            cache._client = None
            cache._initialized = False
    try:
        if kind == "redis":
            redis_url = _redis_url()
            if not redis_url:
                pytest.skip("REDIS_URL not configured; skipping Redis wrapper variant")
            await cache.configure("redis", local_url=redis_url)
        else:
            pg_url = _postgres_test_url()
            if not pg_url:
                pytest.skip("PostgreSQL not configured; skipping Postgres wrapper variant")
            await cache.configure("postgres", database_url=pg_url)
            await cache.clear_pattern("cache:*")
        assert cache.is_initialized
        yield kind
    finally:
        try:
            await cache.close()
        except RuntimeError:
            cache._client = None
            cache._initialized = False
        if prior_initialized and prior_kind == "redis" and _redis_url():
            try:
                await cache.configure("redis", local_url=_redis_url())
            except Exception:  # pragma: no cover - best-effort restore
                pass


@pytest.mark.asyncio
async def test_cached_miss_then_hit(wrapper_cache: str) -> None:
    """The decorator computes once and serves subsequent calls from cache."""
    calls = 0

    @cached(ttl=TTL.SHORT)
    async def load(value: int) -> dict:
        nonlocal calls
        calls += 1
        return {"value": value}

    assert await load(7) == {"value": 7}
    assert calls == 1
    assert await load(7) == {"value": 7}
    assert calls == 1


@pytest.mark.asyncio
async def test_cached_invalidation(wrapper_cache: str) -> None:
    """Clearing the cache pattern forces the wrapped function to recompute."""
    calls = 0

    @cached(ttl=TTL.SHORT)
    async def load(value: str) -> str:
        nonlocal calls
        calls += 1
        return value

    assert await load("a") == "a"
    assert calls == 1
    await cache.clear_pattern("cache:*")
    assert await load("a") == "a"
    assert calls == 2


@pytest.mark.asyncio
async def test_cached_fails_open_when_disabled() -> None:
    """With caching disabled the wrapper never swallows the underlying call."""
    if cache.is_initialized:
        try:
            await cache.close()
        except RuntimeError:
            cache._client = None
            cache._initialized = False
    calls = 0

    @cached(ttl=TTL.SHORT)
    async def load(value: int) -> int:
        nonlocal calls
        calls += 1
        return value

    assert await load(1) == 1
    assert await load(1) == 1
    assert calls == 2
