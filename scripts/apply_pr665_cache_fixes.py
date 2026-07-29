"""Apply the reviewed cache fixes to PR #665.

This script is intentionally exact-match based so it fails rather than modifying
unexpected code if the branch changes before execution.
"""

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    """Replace one exact block, failing if the branch no longer matches."""
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one match in {path}, found {count}: {old[:80]!r}")
    file_path.write_text(text.replace(old, new, 1))


def replace_count(path: str, old: str, new: str, expected: int) -> None:
    """Replace an exact number of identical blocks."""
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"Expected {expected} matches in {path}, found {count}: {old[:80]!r}")
    file_path.write_text(text.replace(old, new))


replace_once(
    "app/cache.py",
    "from __future__ import annotations\n\nimport enum\n",
    "from __future__ import annotations\n\nimport asyncio\nimport enum\n",
)
replace_once(
    "app/cache.py",
    '_SKIP_TYPES = frozenset({"AsyncSession", "Session", "Engine", "Request"})\n\n\nclass TTL',
    '_SKIP_TYPES = frozenset({"AsyncSession", "Session", "Engine", "Request"})\n_CONNECT_TIMEOUT_SECONDS = 5.0\n\n\nclass TTL',
)
replace_once(
    "app/cache.py",
    '''    def record_success(self) -> None:
        """Record successful request."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit '%s': HALF_OPEN -> CLOSED", self.name)
            self._state = CircuitState.CLOSED
            self._failure_count = 0
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

''',
    '''    def reset(self) -> None:
        """Reset the circuit after a confirmed healthy connection."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None

    def record_success(self) -> None:
        """Record successful request."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit '%s': HALF_OPEN -> CLOSED", self.name)
            self.reset()
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

''',
)
replace_once(
    "app/cache.py",
    '''        if local_url:
            try:
                self._client = aioredis.Redis.from_url(local_url, decode_responses=True)
                await self._client.ping()
                self._initialized = True
                self._is_upstash = False
                logger.info("Local Redis cache initialized: %s", local_url)
                return
            except Exception as e:
                logger.error("Failed to initialize local Redis: %s", e)
                self._client = None
                self._initialized = False
                return

''',
    '''        if local_url:
            client = aioredis.Redis.from_url(
                local_url,
                decode_responses=True,
                socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=_CONNECT_TIMEOUT_SECONDS,
            )
            try:
                async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                    await client.ping()
                self._client = client
                self._circuit_breaker.reset()
                self._initialized = True
                self._is_upstash = False
                logger.info("Local Redis cache initialized: %s", local_url)
                return
            except Exception as e:
                logger.error("Failed to initialize local Redis: %s", e)
                try:
                    await client.aclose()
                except Exception:
                    logger.debug("Failed to close unsuccessful Redis client", exc_info=True)
                self._client = None
                self._initialized = False
                return

''',
)
replace_once(
    "app/cache.py",
    '''        if url and token:
            try:
                self._client = UpstashRedis(url=url, token=token)
                await self._client.ping()
                self._initialized = True
                self._is_upstash = True
                logger.info("Upstash Redis cache initialized")
                return
            except Exception as e:
                logger.error("Failed to initialize Upstash Redis: %s", e)
                self._client = None
                self._initialized = False
                return

''',
    '''        if url and token:
            client = UpstashRedis(url=url, token=token)
            try:
                async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                    await client.ping()
                self._client = client
                self._circuit_breaker.reset()
                self._initialized = True
                self._is_upstash = True
                logger.info("Upstash Redis cache initialized")
                return
            except Exception as e:
                logger.error("Failed to initialize Upstash Redis: %s", e)
                self._client = None
                self._initialized = False
                return

''',
)
replace_once(
    "app/cache.py",
    '''            if ttl:
                await self._client.set(key, data, ex=ttl)
            else:
                await self._client.set(key, data)
''',
    '''            if ttl is not None and ttl <= 0:
                await self._client.delete(key)
            elif ttl is not None:
                await self._client.set(key, data, ex=ttl)
            else:
                await self._client.set(key, data)
''',
)

replace_once(
    "app/api/thread.py",
    "from app.api.review import _create_or_update_review_response\n",
    "from app.api.review import _create_or_update_review_response\nfrom app.api.session import _invalidate_session_caches\n",
)
replace_once(
    "app/api/thread.py",
    '''async def _invalidate_thread_caches(user_id: int, thread_id: int | None = None) -> None:
    """Invalidate thread cache entries for a specific user."""
    coros = [invalidate_cache(f"cache:list_threads:User:{user_id}:*")]
    if thread_id is not None:
        coros.append(invalidate_cache(f"cache:get_thread:{thread_id}:User:{user_id}:"))
    await asyncio.gather(*coros)
''',
    '''async def _invalidate_thread_caches(
    user_id: int,
    thread_id: int | None = None,
    *,
    all_details: bool = False,
) -> None:
    """Invalidate thread cache entries for a specific user."""
    coros = [invalidate_cache(f"cache:list_threads:User:{user_id}:*")]
    if all_details:
        coros.append(invalidate_cache(f"cache:get_thread:*:User:{user_id}:"))
    elif thread_id is not None:
        coros.append(invalidate_cache(f"cache:get_thread:{thread_id}:User:{user_id}:"))
    await asyncio.gather(*coros)
''',
)
replace_once(
    "app/api/thread.py",
    '''        await db.delete(thread)
        await db.commit()
        await _invalidate_thread_caches(current_user.id, thread_id)
''',
    '''        await db.delete(thread)
        await db.commit()
        await asyncio.gather(
            _invalidate_thread_caches(current_user.id, all_details=True),
            _invalidate_session_caches(current_user.id),
        )
''',
)
replace_once(
    "app/api/thread.py",
    '''    await db.commit()
    await db.refresh(thread)

    await _invalidate_thread_caches(current_user.id, thread.id)
    return await thread_to_response(thread, db)


@router.post("/{thread_id}/set-pending", response_model=RollResponse)
''',
    '''    await db.commit()
    await db.refresh(thread)

    await asyncio.gather(
        _invalidate_thread_caches(current_user.id, all_details=True),
        _invalidate_session_caches(current_user.id),
    )
    return await thread_to_response(thread, db)


@router.post("/{thread_id}/set-pending", response_model=RollResponse)
''',
)
replace_once(
    "app/api/thread.py",
    '''    await db.commit()

    return RollResponse(
        thread_id=thread_id_int,
''',
    '''    await db.commit()
    await _invalidate_session_caches(current_user.id)

    return RollResponse(
        thread_id=thread_id_int,
''',
)

replace_once(
    "app/api/queue.py",
    '''from app.auth import get_current_user
from app.cache import invalidate_cache
''',
    '''from app.api.session import _invalidate_session_caches
from app.api.thread import _invalidate_thread_caches, thread_to_response
from app.auth import get_current_user
''',
)
replace_once("app/api/queue.py", "from app.api.thread import thread_to_response\n", "")
replace_once(
    "app/api/queue.py",
    '''router = APIRouter()


class PositionRequest''',
    '''router = APIRouter()


async def _invalidate_queue_caches(user_id: int) -> None:
    """Invalidate every cached view affected by queue reordering."""
    await asyncio.gather(
        _invalidate_thread_caches(user_id, all_details=True),
        _invalidate_session_caches(user_id),
    )


class PositionRequest''',
)
replace_count(
    "app/api/queue.py",
    '''    await asyncio.gather(
        invalidate_cache(f"cache:list_threads:User:{current_user.id}:*"),
        invalidate_cache(f"cache:get_thread:{thread_id}:User:{current_user.id}:"),
    )
''',
    '''    await _invalidate_queue_caches(current_user.id)
''',
    3,
)
replace_once(
    "app/api/queue.py",
    '''    await shuffle_queue(current_user.id, db)
    await invalidate_cache(f"cache:list_threads:User:{current_user.id}:*")
''',
    '''    await shuffle_queue(current_user.id, db)
    await _invalidate_queue_caches(current_user.id)
''',
)

replace_once(
    "tests/conftest.py",
    '''    settings = get_redis_settings()
    if settings.redis_url and not cache.is_initialized:
        await cache.initialize(local_url=settings.redis_url)
    yield
''',
    '''    settings = get_redis_settings()
    if settings.redis_url and not cache.is_initialized:
        await cache.initialize(local_url=settings.redis_url)
    if settings.redis_url and not cache.is_initialized:
        pytest.fail("REDIS_URL is configured but the cache failed to initialize")
    yield
''',
)

replace_once(
    "tests/test_cache.py",
    '''    settings = get_redis_settings()
    if settings.redis_url:
        await cache.initialize(local_url=settings.redis_url)
    yield
''',
    '''    settings = get_redis_settings()
    if not settings.redis_url:
        pytest.skip("REDIS_URL is required for cache regression tests")
    await cache.initialize(local_url=settings.redis_url)
    assert cache.is_initialized, "Cache failed to initialize for cache regression tests"
    yield
''',
)
replace_once(
    "tests/test_cache.py",
    '    await cache.set("cache:test_falsy:empty_list:", [], ttl=30)\n',
    '    assert await cache.set("cache:test_falsy:empty_list:", [], ttl=30)\n',
)
replace_once(
    "tests/test_cache.py",
    '    await cache.set("cache:test_falsy:zero:", 0, ttl=30)\n',
    '    assert await cache.set("cache:test_falsy:zero:", 0, ttl=30)\n',
)
replace_once(
    "tests/test_cache.py",
    '    await cache.set("cache:test_set_preservation:", test_set, ttl=30)\n',
    '    assert await cache.set("cache:test_set_preservation:", test_set, ttl=30)\n',
)
replace_once(
    "tests/test_cache.py",
    '    await cache.set("cache:test_nested_set:", test_dict, ttl=30)\n',
    '    assert await cache.set("cache:test_nested_set:", test_dict, ttl=30)\n',
)

cache_tests = Path("tests/test_cache.py")
cache_tests.write_text(
    cache_tests.read_text()
    + '''

@pytest.mark.asyncio
async def test_cache_current_session_warm_then_set_pending(
    auth_client: AsyncClient,
    sample_data: dict,
) -> None:
    """Manual selection invalidates a previously warmed current-session response."""
    thread = sample_data["threads"][0]

    before = await auth_client.get("/api/sessions/current/")
    assert before.status_code == 200

    pending = await auth_client.post(f"/api/threads/{thread.id}/set-pending")
    assert pending.status_code == 200

    after = await auth_client.get("/api/sessions/current/")
    assert after.status_code == 200
    assert after.json()["active_thread"]["id"] == thread.id


@pytest.mark.asyncio
async def test_cache_reinitialize_resets_open_circuit() -> None:
    """A successful reconnect closes an earlier open circuit."""
    from app.cache import CircuitState
    from app.config import get_redis_settings

    settings = get_redis_settings()
    assert settings.redis_url is not None

    for _ in range(cache._circuit_breaker.failure_threshold):
        cache._circuit_breaker.record_failure()
    assert cache._circuit_breaker.state == CircuitState.OPEN

    await cache.close()
    await cache.initialize(local_url=settings.redis_url)

    assert cache.is_initialized
    assert cache._circuit_breaker.state == CircuitState.CLOSED
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
'''
)
