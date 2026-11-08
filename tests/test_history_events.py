"""Tests for history event logging."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("put", "/api/v1/queue/threads/1/position/"),
        ("put", "/api/v1/queue/threads/1/back/"),
        ("put", "/api/queue/threads/1/position/"),
        ("put", "/api/queue/threads/1/back/"),
    ],
)
async def test_retired_queue_move_routes_create_no_reorder_event(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    method: str,
    path: str,
) -> None:
    """Retired queue moves answer 404 and record no reorder event.

    Reorder audit ownership moved to the Rust queue-entry resource: the
    native ``update_queue_entry_moves_front_middle_and_back_with_reorder_events``
    test proves front/middle/back writes record reorder events with the
    reader and thread ids. The retired Python actions must not write an
    event on their 404 path.
    """
    from app.models import Event

    result = await async_db.execute(select(Event).where(Event.type == "reorder"))
    initial_count = len(result.scalars().all())

    kwargs = {"json": {"new_position": 3}} if path.endswith("/position/") else {}
    response = await getattr(auth_client, method)(path, **kwargs)
    assert response.status_code == 404

    result = await async_db.execute(select(Event).where(Event.type == "reorder"))
    assert len(result.scalars().all()) == initial_count


@pytest.mark.asyncio
async def test_delete_thread_creates_event(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Test that deleting a thread creates a delete event.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    from app.models import Event, Thread

    result = await async_db.execute(select(Event).where(Event.type == "delete"))
    initial_delete_count = len(result.scalars().all())

    create_response = await auth_client.post(
        "/api/v1/threads/",
        json={"title": "Test Thread", "format": "Comic", "issues_remaining": 5},
    )
    assert create_response.status_code == 201
    thread_id = create_response.json()["id"]

    thread = await async_db.get(Thread, thread_id)
    assert thread is not None
    owner_id = thread.user_id

    delete_response = await auth_client.delete(f"/api/v1/threads/{thread_id}")
    assert delete_response.status_code == 204

    result = await async_db.execute(select(Event).where(Event.type == "delete"))
    final_delete_events = result.scalars().all()
    final_delete_count = len(final_delete_events)

    assert final_delete_count == initial_delete_count + 1
    assert any(event.user_id == owner_id for event in final_delete_events)

    db_thread = await async_db.get(Thread, thread_id)
    assert db_thread is None


@pytest.mark.asyncio
async def test_retired_shuffle_route_create_no_event(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Retired shuffle actions answer 404 and record no shuffle event.

    Shuffle audit ownership moved to ``POST /api/v2/queue-orders``, which
    records a durable, idempotent queue-order revision in Rust. The retired
    Python shuffle must not write an event on its 404 path.
    """
    from app.models import Event

    result = await async_db.execute(select(Event).where(Event.type == "shuffle"))
    initial_count = len(result.scalars().all())

    response = await auth_client.post("/api/v1/queue/shuffle/")
    assert response.status_code == 404

    result = await async_db.execute(select(Event).where(Event.type == "shuffle"))
    assert len(result.scalars().all()) == initial_count
