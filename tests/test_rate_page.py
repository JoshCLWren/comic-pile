"""Integration tests for rate API endpoint."""

import pytest

from httpx import AsyncClient
from app.models import Event, Session as SessionModel, Thread
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_rate_session_api_returns_thread_info(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /sessions/current/ returns active thread info for rate page."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Amazing Spider-Man",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=4,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "active_thread" in data
    assert data["active_thread"]["id"] == thread.id
    assert data["active_thread"]["title"] == "Amazing Spider-Man"
    assert data["active_thread"]["format"] == "Comic"
    assert data["active_thread"]["issues_remaining"] == 10


@pytest.mark.asyncio
async def test_rate_session_api_returns_die_info(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /sessions/current/ returns die info for dice preview."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=3,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "current_die" in data
    assert data["current_die"] == 10
    assert "last_rolled_result" in data
    assert data["last_rolled_result"] == 3


@pytest.mark.asyncio
async def test_rate_session_api_returns_has_restore_point(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /sessions/current/ returns has_restore_point for session safe indicator."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "has_restore_point" in data
    assert isinstance(data["has_restore_point"], bool)


@pytest.mark.asyncio
async def test_rate_api_invalid_rating(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """POST /rate/ with invalid rating returns 400 error."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = sample_data["threads"][0]
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 6.0, "issues_read": 1})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rate_api_low_rating_moves_to_back(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /rate/ with rating < 4.0 moves thread to back of queue."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread1 = Thread(
        title="Comic 1",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    thread2 = Thread(
        title="Comic 2",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    async_db.add(event)
    await async_db.commit()

    await auth_client.post("/api/rate/", json={"rating": 3.0, "issues_read": 1})

    await async_db.refresh(thread1)
    await async_db.refresh(thread2)
    assert thread1.queue_position > thread2.queue_position


@pytest.mark.asyncio
async def test_rate_api_high_rating_moves_to_front(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /rate/ with rating >= 4.0 moves thread to front of queue."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread1 = Thread(
        title="Comic 1",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    thread2 = Thread(
        title="Comic 2",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    async_db.add(event)
    await async_db.commit()

    await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})

    await async_db.refresh(thread1)
    await async_db.refresh(thread2)
    assert thread1.queue_position < thread2.queue_position


@pytest.mark.asyncio
async def test_rate_api_updates_last_activity_at(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /rate/ updates thread last_activity_at timestamp."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    old_activity_at = thread.last_activity_at

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})

    await async_db.refresh(thread)
    assert thread.last_activity_at is not None
    if old_activity_at:
        assert thread.last_activity_at > old_activity_at


@pytest.mark.asyncio
async def test_rate_api_creates_snapshot(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /rate/ creates snapshot for undo functionality."""
    from tests.conftest import get_or_create_user_async

    from app.models import Snapshot
    from sqlalchemy import select

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    await auth_client.post("/api/rate/", json={"rating": 4.5, "issues_read": 1})

    result = await async_db.execute(select(Snapshot).where(Snapshot.session_id == session.id))
    snapshots = result.scalars().all()
    assert len(snapshots) >= 1
    assert any(s.description is not None and "After rating" in s.description for s in snapshots)


@pytest.mark.asyncio
async def test_rate_api_with_min_rating(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /rate/ accepts minimum rating value (0.5)."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 0.5, "issues_read": 1})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rate_api_with_max_rating(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /rate/ accepts maximum rating value (5.0)."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 5.0, "issues_read": 1})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rate_api_sets_pending_thread_to_next(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /rate/ sets pending_thread_id to next thread when threads remain after rating."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread1 = Thread(
        title="Test Comic 1",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    thread2 = Thread(
        title="Test Comic 2",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    session = SessionModel(start_die=10, user_id=user.id, pending_thread_id=thread1.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    async_db.add(event)
    await async_db.commit()

    await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})

    await async_db.refresh(session)
    assert session.pending_thread_id is not None
    assert session.pending_thread_id != thread1.id


@pytest.mark.asyncio
async def test_rate_api_clears_pending_thread_when_no_threads_remain(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /rate/ clears pending_thread_id to None when no threads remain."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)

    thread2 = Thread(
        title="Test Comic 2",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread)
    await async_db.refresh(thread2)

    session = SessionModel(start_die=10, user_id=user.id, pending_thread_id=thread.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})

    await async_db.refresh(session)
    assert session.pending_thread_id == thread2.id


@pytest.mark.asyncio
async def test_rate_api_sets_pending_thread_to_next_available(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /rate/ sets pending_thread_id to next available thread when multiple threads exist."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread1 = Thread(
        title="Test Comic 1",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread1)

    thread2 = Thread(
        title="Test Comic 2",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    session = SessionModel(start_die=10, user_id=user.id, pending_thread_id=thread1.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    async_db.add(event)
    await async_db.commit()

    await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})

    await async_db.refresh(session)
    assert session.pending_thread_id is not None
    assert session.pending_thread_id != thread1.id


@pytest.mark.asyncio
async def test_rate_api_updates_issues_remaining(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /rate/ correctly decreases issues_remaining."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 2})
    assert response.status_code == 200

    data = response.json()
    assert data["issues_remaining"] == 3

    await async_db.refresh(thread)
    assert thread.issues_remaining == 3


@pytest.mark.asyncio
async def test_rate_api_no_pending_thread_when_finish_session(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /rate/ with finish_session=True does not set pending_thread_id."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    thread2 = Thread(
        title="Thread 2",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    session = SessionModel(start_die=10, user_id=user.id, pending_thread_id=thread1.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    async_db.add(event)
    await async_db.commit()

    await auth_client.post(
        "/api/rate/",
        json={"rating": 4.0, "issues_read": 1, "finish_session": True},
    )

    await async_db.refresh(session)
    assert session.pending_thread_id is None
    assert session.pending_thread_updated_at is None
    assert session.ended_at is not None


@pytest.mark.asyncio
async def test_rate_api_sets_pending_thread_when_not_finish_session(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /rate/ with finish_session=False sets pending_thread_id to next thread."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    thread2 = Thread(
        title="Thread 2",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    async_db.add(event)
    await async_db.commit()

    await auth_client.post(
        "/api/rate/",
        json={"rating": 4.0, "issues_read": 1, "finish_session": False},
    )

    await async_db.refresh(session)
    assert session.pending_thread_id is not None
    assert session.pending_thread_updated_at is not None
