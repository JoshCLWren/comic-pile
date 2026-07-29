"""Warm-cache mutation regression tests.

These tests verify that cache invalidation actually works by:
1. Warming the read cache via a GET request
2. Executing a mutation
3. Repeating the identical GET request
4. Asserting the new value appears (before TTL expiration)
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache
from app.models import Dependency, Issue, Thread
from comic_pile.dependencies import get_blocked_thread_ids


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
        pytest.skip("REDIS_URL is required for cache regression tests")
    await cache.initialize(local_url=settings.redis_url)
    assert cache.is_initialized, "Cache failed to initialize for cache regression tests"
    yield


@pytest.mark.asyncio
async def test_cache_thread_list_warm_then_create(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Warm thread list cache, create thread, verify list updates."""
    await cache.clear_pattern("cache:*")

    # Warm the list cache
    response1 = await auth_client.get("/api/threads/")
    assert response1.status_code == 200
    initial_threads = response1.json()["threads"]

    # Create a new thread
    response = await auth_client.post(
        "/api/threads/",
        json={"title": "Cache Test Thread", "format": "Comic", "issues_remaining": 5},
    )
    assert response.status_code == 201

    # Reread - should reflect new thread (list should be different after invalidation)
    response2 = await auth_client.get("/api/threads/")
    assert response2.status_code == 200
    new_threads = response2.json()["threads"]
    assert len(new_threads) == len(initial_threads) + 1 or new_threads != initial_threads


@pytest.mark.asyncio
async def test_cache_thread_detail_warm_then_update(
    auth_client: AsyncClient,
    sample_data: dict,
) -> None:
    """Warm thread detail cache, update thread, verify detail updates."""
    await cache.clear_pattern("cache:*")
    thread = sample_data["threads"][0]

    # Warm the detail cache
    response1 = await auth_client.get(f"/api/threads/{thread.id}")
    assert response1.status_code == 200
    assert response1.json()["title"] == thread.title

    new_title = "Superman (Updated)"
    response = await auth_client.put(
        f"/api/threads/{thread.id}",
        json={"title": new_title, "format": "Comic", "issues_remaining": 10},
    )
    assert response.status_code == 200

    # Reread - should reflect new title
    response2 = await auth_client.get(f"/api/threads/{thread.id}")
    assert response2.status_code == 200
    assert response2.json()["title"] == new_title


@pytest.mark.asyncio
async def test_cache_session_details_warm_then_rate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Warm session details, rate a thread, verify new event appears."""
    await cache.clear_pattern("cache:*")

    from app.models import Thread as ThreadModel

    thread = ThreadModel(
        title="Rate Session Test",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
    )
    async_db.add(thread)
    await async_db.commit()

    # Roll dice first so rate endpoint has an active thread
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200

    # Determine which session is active after the roll
    current_resp = await auth_client.get("/api/sessions/current/")
    assert current_resp.status_code == 200
    active_session_id = current_resp.json()["id"]

    # Warm session details cache using the active session
    response1 = await auth_client.get(f"/api/sessions/{active_session_id}/details")
    assert response1.status_code == 200
    initial_event_count = len(response1.json()["events"])

    # Rate a thread
    rate_response = await auth_client.post(
        "/api/rate/",
        json={
            "rating": 4,
            "finish_session": False,
        },
    )
    assert rate_response.status_code == 200

    # Reread session details - should include new rate event
    response2 = await auth_client.get(f"/api/sessions/{active_session_id}/details")
    assert response2.status_code == 200
    assert len(response2.json()["events"]) > initial_event_count


@pytest.mark.asyncio
async def test_cache_session_snapshots_warm_then_rate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Warm snapshot list, rate a thread, verify new snapshot appears."""
    await cache.clear_pattern("cache:*")

    from app.models import Thread as ThreadModel

    thread = ThreadModel(
        title="Snap Session Test",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
    )
    async_db.add(thread)
    await async_db.commit()

    # Roll dice first so rate endpoint has an active thread
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200

    # Determine which session is active after the roll
    current_resp = await auth_client.get("/api/sessions/current/")
    assert current_resp.status_code == 200
    active_session_id = current_resp.json()["id"]

    # Warm snapshot cache using the active session
    response1 = await auth_client.get(f"/api/sessions/{active_session_id}/snapshots")
    assert response1.status_code == 200
    initial_count = len(response1.json()["snapshots"])

    # Rate
    rate_response = await auth_client.post(
        "/api/rate/",
        json={
            "rating": 4,
            "finish_session": False,
        },
    )
    assert rate_response.status_code == 200

    # Reread - should include new snapshot
    response2 = await auth_client.get(f"/api/sessions/{active_session_id}/snapshots")
    assert response2.status_code == 200
    assert len(response2.json()["snapshots"]) > initial_count


@pytest.mark.asyncio
async def test_cache_blocking_info_warm_then_mark_read(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Warm blocking info, mark source issue read, verify target unblocked."""
    await cache.clear_pattern("cache:*")

    user = None
    from app.models.user import User

    result = await async_db.execute(
        select(User).where(User.username == "testuser")
    )
    user = result.scalar_one_or_none()
    if not user:
        result = await async_db.execute(select(User).limit(1))
        user = result.scalar_one()

    a = Thread(
        title="Blocking Thread A",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    b = Thread(
        title="Blocked Thread B",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    async_db.add_all([a, b])
    await async_db.flush()
    for t in (a, b):
        await async_db.refresh(t)

    issue_a = Issue(
        thread_id=a.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    issue_b = Issue(
        thread_id=b.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add_all([issue_a, issue_b])
    await async_db.flush()
    for iss in (issue_a, issue_b):
        await async_db.refresh(iss)

    from sqlalchemy import update

    await async_db.execute(
        update(Thread)
        .where(Thread.id == a.id)
        .values(next_unread_issue_id=issue_a.id)
    )
    await async_db.execute(
        update(Thread)
        .where(Thread.id == b.id)
        .values(next_unread_issue_id=issue_b.id)
    )

    dependency = Dependency(
        source_issue_id=issue_a.id,
        target_issue_id=issue_b.id,
    )
    async_db.add(dependency)
    await async_db.commit()

    from comic_pile.dependencies import refresh_user_blocked_status
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    # Warm blocking info for B
    response1 = await auth_client.post(f"/api/v1/threads/{b.id}:getBlockingInfo")
    assert response1.status_code == 200
    assert response1.json()["is_blocked"] is True
    assert len(response1.json()["blocking_reasons"]) > 0

    # Mark source issue read
    mark_response = await auth_client.post(
        f"/api/v1/issues/{issue_a.id}:markRead"
    )
    assert mark_response.status_code == 204

    # Reread blocking info - should now show unblocked
    response2 = await auth_client.post(f"/api/v1/threads/{b.id}:getBlockingInfo")
    assert response2.status_code == 200
    assert response2.json()["is_blocked"] is False
    assert response2.json()["blocking_reasons"] == []


@pytest.mark.asyncio
async def test_cache_get_blocked_thread_ids_returns_set(
    async_db: AsyncSession,
    sample_data: dict,
) -> None:
    """Verify get_blocked_thread_ids returns a set (not list) on both hit and miss."""
    user = sample_data["user"]

    await cache.clear_pattern("cache:*")

    result1 = await get_blocked_thread_ids(user.id, async_db)
    assert isinstance(result1, set), f"Expected set, got {type(result1)}"

    result2 = await get_blocked_thread_ids(user.id, async_db)
    assert isinstance(result2, set), f"Expected set on cache hit, got {type(result2)}"


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
