"""Tests for roll API endpoints."""


import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.roll_flow import roll_pending_thread


@pytest.mark.asyncio
async def test_roll_success(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """The retained Roll flow returns a valid thread."""
    data = await roll_pending_thread(async_db)

    assert data.title
    assert data.die_size == 8
    assert 1 <= data.result <= 8

    thread_ids = [t.id for t in sample_data["threads"] if t.status == "active"]
    assert data.thread_id in thread_ids


@pytest.mark.asyncio
async def test_roll_override(auth_client: AsyncClient, sample_data: dict) -> None:
    """POST /roll/override/ sets specific thread."""
    _ = sample_data
    thread_id = 1
    response = await auth_client.post("/api/v1/roll/override", json={"thread_id": thread_id})
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == thread_id
    assert data["title"] == "Superman"
    assert data["die_size"] == 8
    assert data["result"] == 0


@pytest.mark.asyncio
async def test_roll_no_pool(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Returns error if no active threads."""
    from tests.conftest import get_or_create_user_async

    await get_or_create_user_async(async_db)

    with pytest.raises(HTTPException) as exc_info:
        await roll_pending_thread(async_db)
    assert exc_info.value.status_code == 400
    assert "No active threads" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_roll_overflow(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Roll works correctly when thread count < die size."""
    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Only Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    data = await roll_pending_thread(async_db)
    assert data.thread_id == thread.id
    assert 1 <= data.result <= 1


@pytest.mark.asyncio
async def test_dismiss_pending_clears_pending_thread(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """POST /roll/dismiss-pending clears pending thread in current session."""
    _ = sample_data

    await roll_pending_thread(async_db)

    before_session = await auth_client.get("/api/v1/sessions/current/")
    assert before_session.status_code == 200
    assert before_session.json()["pending_thread_id"] is not None

    dismiss_response = await auth_client.post("/api/v1/roll/dismiss-pending")
    assert dismiss_response.status_code == 204

    after_session = await auth_client.get("/api/v1/sessions/current/")
    assert after_session.status_code == 200
    assert after_session.json()["pending_thread_id"] is None


@pytest.mark.asyncio
async def test_dismiss_pending_when_no_pending_exists(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """POST /roll/dismiss-pending is idempotent when no pending thread exists."""
    _ = sample_data

    before_session = await auth_client.get("/api/v1/sessions/current/")
    assert before_session.status_code == 200
    assert before_session.json()["pending_thread_id"] is None

    dismiss_response = await auth_client.post("/api/v1/roll/dismiss-pending")
    assert dismiss_response.status_code == 204

    after_session = await auth_client.get("/api/v1/sessions/current/")
    assert after_session.status_code == 200
    assert after_session.json()["pending_thread_id"] is None


@pytest.mark.asyncio
async def test_roll_override_nonexistent(auth_client: AsyncClient, sample_data: dict) -> None:
    """Override returns 404 for non-existent thread."""
    _ = sample_data
    response = await auth_client.post("/api/v1/roll/override", json={"thread_id": 999})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_override_roll_blocked_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Override roll returns 422 for blocked threads."""
    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    blocked_thread = Thread(
        title="Blocked Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        is_blocked=True,
        user_id=user.id,
    )
    async_db.add(blocked_thread)
    await async_db.commit()
    await async_db.refresh(blocked_thread)

    response = await auth_client.post("/api/v1/roll/override", json={"thread_id": blocked_thread.id})
    assert response.status_code == 422
    assert "blocked" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_override_roll_completed_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Override roll returns 422 for completed threads."""
    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    completed_thread = Thread(
        title="Completed Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="completed",
        is_blocked=False,
        user_id=user.id,
    )
    async_db.add(completed_thread)
    await async_db.commit()
    await async_db.refresh(completed_thread)

    response = await auth_client.post("/api/v1/roll/override", json={"thread_id": completed_thread.id})
    assert response.status_code == 422
    assert "completed" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_roll_die_boundary_caps_result(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Roll result stays within current_die even when the pool is larger.

    Verifies that the bounded candidate pool acts as a hard ceiling: the API
    must never return a die result greater than the current die face count.
    """
    from datetime import UTC, datetime

    from app.models import ReadingSession, Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)

    # auth_client does not create a session; the roll endpoint resolves one lazily,
    # so create the authoritative open session up front.
    session = ReadingSession(
        user_id=user.id,
        start_die=8,
        started_at=now,
        manual_die=4,
    )
    async_db.add(session)
    await async_db.commit()

    threads = [
        Thread(
            title=f"Pool Thread {i}",
            format="Comic",
            issues_remaining=3,
            queue_position=i + 1,
            status="active",
            user_id=user.id,
            created_at=now,
        )
        for i in range(8)
    ]
    async_db.add_all(threads)
    await async_db.commit()

    data = await roll_pending_thread(async_db)
    assert data.die_size == 4
    assert 1 <= data.result <= 4


@pytest.mark.asyncio
async def test_roll_d20_includes_all_available_threads(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A d20 die does not fabricate candidates beyond the available pool.

    When the active pool is smaller than the die face count the bounded pool
    must be the entire eligible pool, not empty.
    """
    from datetime import UTC, datetime

    from app.models import ReadingSession, Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)

    # auth_client does not create a session; the roll endpoint resolves one lazily,
    # so create the authoritative open session up front.
    session = ReadingSession(
        user_id=user.id,
        start_die=8,
        started_at=now,
        manual_die=20,
    )
    async_db.add(session)
    await async_db.commit()

    threads = [
        Thread(
            title=f"d20 Thread {i}",
            format="Comic",
            issues_remaining=2,
            queue_position=i + 1,
            status="active",
            user_id=user.id,
            created_at=now,
        )
        for i in range(6)
    ]
    async_db.add_all(threads)
    await async_db.commit()

    data = await roll_pending_thread(async_db)
    assert data.die_size == 20
    assert 1 <= data.result <= 6


@pytest.mark.asyncio
async def test_roll_snoozed_thread_excluded_from_pool(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A snoozed thread is excluded from the bounded roll pool before selection.

    Threads in the session's snoozed list must not count toward pool size and
    must not be selectable during that roll.
    """
    from datetime import UTC, datetime

    from app.models import ReadingSession, Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)

    # auth_client does not create a session; the roll endpoint resolves one lazily,
    # so create the authoritative open session up front.
    session = ReadingSession(
        user_id=user.id,
        start_die=8,
        started_at=now,
        manual_die=4,
    )
    async_db.add(session)
    await async_db.commit()

    snoozed_thread = Thread(
        title="Snoozed Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=now,
    )
    active_threads = [
        Thread(
            title=f"Active Thread {i}",
            format="Comic",
            issues_remaining=2,
            queue_position=i + 2,
            status="active",
            user_id=user.id,
            created_at=now,
        )
        for i in range(5)
    ]
    async_db.add(snoozed_thread)
    async_db.add_all(active_threads)
    await async_db.commit()
    await async_db.refresh(snoozed_thread)

    session.snoozed_thread_ids = [snoozed_thread.id]
    await async_db.commit()

    data = await roll_pending_thread(async_db)
    assert data.die_size == 4
    assert 1 <= data.result <= 4
    assert data.thread_id != snoozed_thread.id


@pytest.mark.asyncio
async def test_retired_set_die_endpoint_not_found(auth_client: AsyncClient) -> None:
    """POST /api/v1/roll/set-die was retired (#4352). Returns 404."""
    response = await auth_client.post("/api/v1/roll/set-die?die=20")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_retired_clear_manual_die_endpoint_not_found(auth_client: AsyncClient) -> None:
    """POST /api/v1/roll/clear-manual-die was retired (#4353). Returns 404."""
    response = await auth_client.post("/api/v1/roll/clear-manual-die")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_retired_session_mode_endpoint_not_found(auth_client: AsyncClient) -> None:
    """PATCH /api/v1/roll/session-mode was retired (#4354). Returns 404."""
    response = await auth_client.patch(
        "/api/v1/roll/session-mode",
        json={"bandwidth": "momentum"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/roll/", "/api/roll/"])
async def test_retired_roll_mutation_endpoint_not_found(
    auth_client: AsyncClient, path: str
) -> None:
    """POST /api/v1/roll/ was retired (#4336). Both aliases return 404."""
    response = await auth_client.post(path)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/v1/roll/", "post"),
        ("/api/v1/roll/set-die", "post"),
        ("/api/v1/roll/clear-manual-die", "post"),
        ("/api/v1/roll/session-mode", "patch"),
    ],
)
async def test_retired_roll_mutation_absent_from_openapi(
    auth_client: AsyncClient, path: str, method: str
) -> None:
    """Retired Roll mutations are no longer advertised as active capabilities."""
    response = await auth_client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert method not in paths.get(path, {})
