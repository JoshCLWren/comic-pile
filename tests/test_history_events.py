"""Tests for history event logging."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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
