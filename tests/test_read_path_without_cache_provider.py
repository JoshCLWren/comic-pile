"""Read-path behavior coverage with no application-cache read in place.

Issue #2972 removed ``@cached(...)`` from every production backend read path so
those endpoints execute their database/service logic directly. These tests pin
the two halves of that contract:

1. Every de-cached read still returns the same user-visible result, including
   read-after-write freshness for the endpoints that previously relied on
   invalidation to look correct.
2. A de-cached read issues **zero** remote cache commands, even when a cache
   provider is fully configured. The recorder below swaps in a fake backend on
   the process-wide cache router, so any decorator that had survived removal
   would be observable as a recorded command.

No live Redis is required: the recorder replaces the provider outright, and the
endpoint assertions run entirely against the test database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache
from app.models import Dependency, Issue, Thread, User
from comic_pile.dependencies import get_blocked_thread_ids


@dataclass
class RecordingCacheBackend:
    """Fake cache provider that records every remote command it receives."""

    calls: list[str] = field(default_factory=list)
    generations: dict[str, int] = field(default_factory=dict)
    values: dict[str, object] = field(default_factory=dict)

    @property
    def is_initialized(self) -> bool:
        """Report an initialized provider so any surviving decorator engages."""
        return True

    def record(self, command: str) -> None:
        """Record one remote cache command name."""
        self.calls.append(command)

    async def ping(self) -> None:
        """Accept a liveness probe without contacting a real provider."""
        self.record("ping")

    async def get(self, key: str) -> object | None:
        """Return a stored value, recording the read."""
        self.record("get")
        return self.values.get(key)

    async def set(self, key: str, value: object, ttl: int | None = None) -> bool:
        """Store a value, recording the write."""
        self.record("set")
        self.values[key] = value
        return True

    async def delete(self, key: str) -> bool:
        """Delete a value, recording the delete."""
        self.record("delete")
        return self.values.pop(key, None) is not None

    async def clear_pattern(self, pattern: str) -> int:
        """Clear matching values, recording the sweep."""
        self.record("clear_pattern")
        return 0

    async def incr(self, key: str) -> int:
        """Advance and return one generation counter."""
        self.record("incr")
        self.generations[key] = self.generations.get(key, 0) + 1
        return self.generations[key]

    async def get_generation(self, key: str) -> int:
        """Return one generation counter without creating it."""
        self.record("get_generation")
        return self.generations.get(key, 0)

    async def eval_script(self, script: str, keys: list[str], args: list[str]) -> object:
        """Return a guaranteed cache miss for the generation/value script."""
        self.record("eval_script")
        return [str(self.generations.get(keys[0], 0)), None]

    async def atomic_generation_read(
        self, generation_key: str, value_prefix: str, normalized: str
    ) -> list[object]:
        """Return a guaranteed cache miss for the Postgres-shaped read."""
        self.record("atomic_generation_read")
        return [self.generations.get(generation_key, 0), None]

    def decode_value(self, raw: object) -> object:
        """Return the recorded value unchanged."""
        return raw

    def record_failure(self) -> None:
        """Accept a circuit-breaker failure notification."""


@pytest_asyncio.fixture
async def cache_recorder(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[RecordingCacheBackend]:
    """Install a recording cache provider for the duration of one test."""
    recorder = RecordingCacheBackend()
    monkeypatch.setattr(cache, "_backend", recorder, raising=False)
    monkeypatch.setattr(cache, "_provider_kind", "redis", raising=False)
    monkeypatch.setattr(cache, "_demoted", False, raising=False)
    monkeypatch.setattr(cache, "_client", None, raising=False)
    yield recorder


def _assert_zero_cache_commands(recorder: RecordingCacheBackend, label: str) -> None:
    """Assert a de-cached read issued no remote cache command."""
    assert recorder.calls == [], f"{label} issued cache commands: {recorder.calls}"


async def _authenticated_user_id(async_db: AsyncSession, test_username: str) -> int:
    """Return the user ID created by the authenticated client fixture."""
    result = await async_db.execute(select(User.id).where(User.username == test_username))
    return result.scalar_one()


async def _resolve_user(async_db: AsyncSession) -> User:
    """Return the first available user, preferring the default test account."""
    result = await async_db.execute(select(User).where(User.username == "testuser"))
    user = result.scalar_one_or_none()
    if user is not None:
        return user
    result = await async_db.execute(select(User).limit(1))
    found = result.scalar_one()
    assert isinstance(found, User)
    return found


# ---------------------------------------------------------------------------
# Thread read paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thread_list_reads_fresh_data_without_cache(
    auth_client: AsyncClient,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """``GET /api/v1/threads/`` reflects a newly created thread with no cache read."""
    first = await auth_client.get("/api/v1/threads/")
    assert first.status_code == 200
    initial_titles = {item["title"] for item in first.json()["threads"]}
    cache_recorder.calls.clear()

    created = await auth_client.post(
        "/api/v1/threads/",
        json={"title": "Uncached Create", "format": "Comic", "issues_remaining": 5},
    )
    assert created.status_code == 201
    cache_recorder.calls.clear()

    second = await auth_client.get("/api/v1/threads/")
    assert second.status_code == 200
    new_titles = {item["title"] for item in second.json()["threads"]}

    assert new_titles == initial_titles | {"Uncached Create"}
    _assert_zero_cache_commands(cache_recorder, "GET /api/v1/threads/")


@pytest.mark.asyncio
async def test_thread_detail_reads_fresh_data_without_cache(
    auth_client: AsyncClient,
    sample_data: dict,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """``GET /api/v1/threads/{id}`` reflects an update with no cache read."""
    thread = sample_data["threads"][0]

    first = await auth_client.get(f"/api/v1/threads/{thread.id}")
    assert first.status_code == 200
    assert first.json()["title"] == thread.title
    cache_recorder.calls.clear()

    updated = await auth_client.put(
        f"/api/v1/threads/{thread.id}",
        json={"title": "Uncached Update", "format": "Comic", "issues_remaining": 10},
    )
    assert updated.status_code == 200
    cache_recorder.calls.clear()

    second = await auth_client.get(f"/api/v1/threads/{thread.id}")
    assert second.status_code == 200
    assert second.json()["title"] == "Uncached Update"
    _assert_zero_cache_commands(cache_recorder, f"GET /api/v1/threads/{thread.id}")


@pytest.mark.asyncio
async def test_completed_thread_list_reads_without_cache(
    auth_client: AsyncClient,
    sample_data: dict,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """The completed-thread listing still returns its paginated envelope."""
    response = await auth_client.get("/api/v1/threads/completed/threads")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["threads"], list)
    assert "next_page_token" in body
    assert {item["title"] for item in body["threads"]} == {"Wonder Woman"}
    _assert_zero_cache_commands(cache_recorder, "GET /api/v1/threads/completed/threads")


# ---------------------------------------------------------------------------
# Issue read paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_list_reads_fresh_data_without_cache(
    auth_client: AsyncClient,
    sample_data: dict,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """``GET /threads/{id}/issues`` paginates directly from the database."""
    thread = sample_data["threads"][1]

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == len(body["issues"])
    assert body["page_size"] > 0

    unread = await auth_client.get(f"/api/v1/threads/{thread.id}/issues?status=unread")
    assert unread.status_code == 200
    assert all(issue["status"] == "unread" for issue in unread.json()["issues"])

    _assert_zero_cache_commands(cache_recorder, f"GET /api/v1/threads/{thread.id}/issues")


@pytest.mark.asyncio
async def test_issue_detail_and_order_validation_read_without_cache(
    auth_client: AsyncClient,
    sample_data: dict,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """Single-issue reads and order validation stay correct without a cache."""
    thread = sample_data["threads"][1]

    listed = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    issue_id = listed.json()["issues"][0]["id"]

    detail = await auth_client.get(f"/api/v1/issues/{issue_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == issue_id

    order = await auth_client.get(f"/api/v1/threads/{thread.id}/issues:validateOrder")
    assert order.status_code == 200
    assert isinstance(order.json()["warnings"], list)

    _assert_zero_cache_commands(
        cache_recorder, f"GET /api/v1/issues/{issue_id} + validateOrder"
    )


@pytest.mark.asyncio
async def test_issue_reads_are_owner_scoped_without_cache(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """A read that never hits the cache must still enforce ownership.

    Cache removal must not weaken the ownership filter: a second user reading
    the same identifiers gets 404s and still issues zero cache commands.
    """
    from app.auth import create_access_token

    thread = sample_data["threads"][1]
    listed = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    issue_id = listed.json()["issues"][0]["id"]
    cache_recorder.calls.clear()

    outsider = User(username="issue-scope-probe")
    async_db.add(outsider)
    await async_db.commit()
    await async_db.refresh(outsider)

    async with AsyncClient(
        transport=auth_client._transport, base_url=auth_client.base_url
    ) as other:
        other.headers.update(auth_client.headers)
        other.cookies.update(auth_client.cookies)
        other.headers["Authorization"] = (
            f"Bearer {create_access_token(data={'sub': outsider.username, 'jti': 'scope'})}"
        )

        assert (await other.get(f"/api/v1/issues/{issue_id}")).status_code == 404
        assert (await other.get(f"/api/v1/threads/{thread.id}/issues")).status_code == 404
        assert (await other.get(f"/api/v1/threads/{thread.id}/dependencies")).status_code == 404
        assert (await other.get("/api/v1/dependencies/blocked")).status_code == 200

    _assert_zero_cache_commands(cache_recorder, "cross-owner read endpoints")


# ---------------------------------------------------------------------------
# Dependency and blocked-thread read paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dependency_reads_without_cache(
    auth_client: AsyncClient,
    sample_data: dict,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """Dependency reads return their envelopes directly from the database."""
    thread = sample_data["threads"][1]

    dependencies = await auth_client.get(f"/api/v1/threads/{thread.id}/dependencies")
    assert dependencies.status_code == 200
    assert dependencies.json() == {"blocking": [], "blocked_by": []}

    order_check = await auth_client.get(f"/api/v1/threads/{thread.id}/dependency-order-check")
    assert order_check.status_code == 200
    assert order_check.json() == {"thread_id": thread.id, "conflicts": []}

    connected = await auth_client.get(f"/api/v1/threads/{thread.id}/connected")
    assert connected.status_code == 200
    assert connected.json() == {"thread_id": thread.id, "connected_threads": []}

    _assert_zero_cache_commands(cache_recorder, "GET dependency endpoints")


@pytest.mark.asyncio
async def test_issue_dependency_read_without_cache(
    auth_client: AsyncClient,
    sample_data: dict,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """``GET /issues/{id}/dependencies`` resolves without a cache read."""
    thread = sample_data["threads"][1]
    listed = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    issue_id = listed.json()["issues"][0]["id"]

    response = await auth_client.get(f"/api/v1/issues/{issue_id}/dependencies")
    assert response.status_code == 200
    body = response.json()
    assert body["issue_id"] == issue_id
    assert body["incoming"] == []
    assert body["outgoing"] == []
    _assert_zero_cache_commands(cache_recorder, f"GET /api/v1/issues/{issue_id}/dependencies")


@pytest.mark.asyncio
async def test_blocking_info_reads_fresh_data_without_cache(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """Blocking info reflects a newly read source issue with no cache read."""
    user = await _resolve_user(async_db)

    source = Thread(
        title="Uncached Source",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    target = Thread(
        title="Uncached Target",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    async_db.add_all([source, target])
    await async_db.flush()
    await async_db.refresh(source)
    await async_db.refresh(target)

    source_issue = Issue(thread_id=source.id, issue_number="1", position=1, status="unread")
    target_issue = Issue(thread_id=target.id, issue_number="1", position=1, status="unread")
    async_db.add_all([source_issue, target_issue])
    await async_db.flush()
    await async_db.refresh(source_issue)
    await async_db.refresh(target_issue)

    await async_db.execute(
        update(Thread)
        .where(Thread.id.in_([source.id, target.id]))
        .values(next_unread_issue_id=None)
    )
    await async_db.execute(
        update(Thread).where(Thread.id == source.id).values(next_unread_issue_id=source_issue.id)
    )
    await async_db.execute(
        update(Thread).where(Thread.id == target.id).values(next_unread_issue_id=target_issue.id)
    )
    async_db.add(
        Dependency(source_issue_id=source_issue.id, target_issue_id=target_issue.id)
    )
    await async_db.commit()

    from comic_pile.dependencies import refresh_user_blocked_status

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    cache_recorder.calls.clear()

    blocked = await auth_client.post(f"/api/v1/threads/{target.id}:getBlockingInfo")
    assert blocked.status_code == 200
    assert blocked.json()["is_blocked"] is True
    assert len(blocked.json()["blocking_reasons"]) > 0
    _assert_zero_cache_commands(cache_recorder, f"POST /api/v1/threads/{target.id}:getBlockingInfo")

    batch = await auth_client.post(
        "/api/v1/threads:getBlockingInfo",
        json={"thread_ids": [target.id]},
    )
    assert batch.status_code == 200
    _assert_zero_cache_commands(cache_recorder, "POST /api/v1/threads:getBlockingInfo")

    marked = await auth_client.post(f"/api/v1/issues/{source_issue.id}:markRead")
    assert marked.status_code == 204
    cache_recorder.calls.clear()

    after = await auth_client.post(f"/api/v1/threads/{target.id}:getBlockingInfo")
    assert after.status_code == 200
    assert after.json()["is_blocked"] is False
    assert after.json()["blocking_reasons"] == []
    _assert_zero_cache_commands(cache_recorder, f"POST /api/v1/threads/{target.id}:getBlockingInfo")


@pytest.mark.asyncio
async def test_get_blocked_thread_ids_reads_directly_from_database(
    async_db: AsyncSession,
    sample_data: dict,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """``get_blocked_thread_ids`` returns a set and issues no cache command."""
    user = sample_data["user"]

    first = await get_blocked_thread_ids(user.id, async_db)
    assert isinstance(first, set)
    _assert_zero_cache_commands(cache_recorder, "get_blocked_thread_ids")

    second = await get_blocked_thread_ids(user.id, async_db)
    assert second == first
    _assert_zero_cache_commands(cache_recorder, "get_blocked_thread_ids (repeat)")


@pytest.mark.asyncio
async def test_blocked_thread_ids_endpoint_without_cache(
    auth_client: AsyncClient,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """``GET /api/v1/dependencies/blocked`` returns a list of integers."""
    response = await auth_client.get("/api/v1/dependencies/blocked")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    _assert_zero_cache_commands(cache_recorder, "GET /api/v1/dependencies/blocked")


# ---------------------------------------------------------------------------
# Session read paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_history_reads_without_cache(
    auth_client: AsyncClient,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """The session history listing paginates directly from the database."""
    response = await auth_client.get("/api/v1/sessions/")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["sessions"], list)
    assert "next_page_token" in body
    _assert_zero_cache_commands(cache_recorder, "GET /api/v1/sessions/")


@pytest.mark.asyncio
async def test_current_session_reads_fresh_data_without_cache(
    auth_client: AsyncClient,
    sample_data: dict,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """``GET /api/v1/sessions/current/`` reflects a newly set pending thread."""
    thread = sample_data["threads"][0]

    before = await auth_client.get("/api/v1/sessions/current/")
    assert before.status_code == 200
    cache_recorder.calls.clear()

    pending = await auth_client.post(f"/api/v1/threads/{thread.id}/set-pending")
    assert pending.status_code == 200
    cache_recorder.calls.clear()

    after = await auth_client.get("/api/v1/sessions/current/")
    assert after.status_code == 200
    assert after.json()["active_thread"]["id"] == thread.id
    _assert_zero_cache_commands(cache_recorder, "GET /api/v1/sessions/current/")


@pytest.mark.asyncio
async def test_session_detail_reads_fresh_events_without_cache(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    test_username: str,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """Session details and snapshots gain new rows with no cache read."""
    user_id = await _authenticated_user_id(async_db, test_username)
    async_db.add(
        Thread(
            title="Uncached Session Thread",
            format="Comic",
            issues_remaining=5,
            queue_position=1,
            status="active",
            user_id=user_id,
        )
    )
    await async_db.commit()

    rolled = await auth_client.post("/api/v1/roll/")
    assert rolled.status_code == 200

    current = await auth_client.get("/api/v1/sessions/current/")
    assert current.status_code == 200
    session_id = current.json()["id"]
    cache_recorder.calls.clear()

    details_before = await auth_client.get(f"/api/v1/sessions/{session_id}/details")
    assert details_before.status_code == 200
    initial_events = len(details_before.json()["events"])
    snapshots_before = await auth_client.get(f"/api/v1/sessions/{session_id}/snapshots")
    assert snapshots_before.status_code == 200
    initial_snapshots = len(snapshots_before.json()["snapshots"])
    cache_recorder.calls.clear()

    rated = await auth_client.post("/api/v1/rate/", json={"rating": 4, "finish_session": False})
    assert rated.status_code == 200
    cache_recorder.calls.clear()

    details_after = await auth_client.get(f"/api/v1/sessions/{session_id}/details")
    assert details_after.status_code == 200
    snapshots_after = await auth_client.get(f"/api/v1/sessions/{session_id}/snapshots")
    assert snapshots_after.status_code == 200

    assert len(details_after.json()["events"]) > initial_events
    assert len(snapshots_after.json()["snapshots"]) > initial_snapshots
    _assert_zero_cache_commands(cache_recorder, f"GET /api/v1/sessions/{session_id}/details")


@pytest.mark.asyncio
async def test_session_detail_lookup_without_cache(
    auth_client: AsyncClient,
    cache_recorder: RecordingCacheBackend,
) -> None:
    """``GET /api/v1/sessions/{id}`` resolves directly from the database."""
    current = await auth_client.get("/api/v1/sessions/current/")
    assert current.status_code == 200
    session_id = current.json()["id"]
    cache_recorder.calls.clear()

    response = await auth_client.get(f"/api/v1/sessions/{session_id}")
    assert response.status_code == 200
    assert response.json()["id"] == session_id
    _assert_zero_cache_commands(cache_recorder, f"GET /api/v1/sessions/{session_id}")
