"""Tests for reading order item insertion endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.database import get_db
from app.main import app
from app.models import Thread
from app.models.reading_order import ReadingOrder, ReadingOrderItem


@pytest_asyncio.fixture
async def insert_client(async_db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Authenticated HTTP client for insert endpoint tests."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield async_db

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        csrf_token = generate_csrf_token()
        ac.cookies.set(CSRF_COOKIE_NAME, csrf_token)
        ac.headers.update({CSRF_HEADER_NAME: csrf_token})
        token = create_access_token(data={"sub": user.username, "jti": "test"})
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac
    app.dependency_overrides.clear()


async def _make_thread(async_db: AsyncSession, *, user_id: int, title: str) -> Thread:
    """Create and persist a minimal owned thread."""
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


async def _make_reading_order(
    async_db: AsyncSession, *, user_id: int, name: str
) -> ReadingOrder:
    """Create and persist a minimal reading order."""
    order = ReadingOrder(name=name, user_id=user_id)
    async_db.add(order)
    await async_db.flush()
    return order


@pytest.mark.asyncio
async def test_insert_item_into_empty_order(insert_client: AsyncClient, async_db: AsyncSession) -> None:
    """Inserting into an empty reading order places the item at position 1."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    thread = await _make_thread(async_db, user_id=user.id, title="Batman #1")
    order = await _make_reading_order(async_db, user_id=user.id, name="DC Reading Order")
    await async_db.commit()

    response = await insert_client.post(
        f"/api/v1/reading-orders/{order.id}/items",
        json={"thread_id": thread.id, "position": 1},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["reading_order_id"] == order.id
    assert data["thread_id"] == thread.id
    assert data["position"] == 1
    assert data["total_items"] == 1


@pytest.mark.asyncio
async def test_insert_item_shifts_existing(insert_client: AsyncClient, async_db: AsyncSession) -> None:
    """Inserting at an existing position shifts later items."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    t1 = await _make_thread(async_db, user_id=user.id, title="Batman #1")
    t2 = await _make_thread(async_db, user_id=user.id, title="Batman #2")
    t3 = await _make_thread(async_db, user_id=user.id, title="Batman #3")
    order = await _make_reading_order(async_db, user_id=user.id, name="Order")
    await async_db.flush()

    for i, thread in enumerate([t1, t2, t3], start=1):
        async_db.add(ReadingOrderItem(reading_order_id=order.id, thread_id=thread.id, position=i))
    await async_db.commit()

    response = await insert_client.post(
        f"/api/v1/reading-orders/{order.id}/items",
        json={"thread_id": t3.id, "position": 2},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["position"] == 2
    assert data["total_items"] == 3

    result = await async_db.execute(
        select(ReadingOrderItem)
        .where(ReadingOrderItem.reading_order_id == order.id)
        .order_by(ReadingOrderItem.position)
    )
    items = result.scalars().all()
    positions = {item.thread_id: item.position for item in items}
    assert positions[t1.id] == 1
    assert positions[t3.id] == 2
    assert positions[t2.id] == 3


@pytest.mark.asyncio
async def test_insert_item_nonexistent_order(insert_client: AsyncClient, async_db: AsyncSession) -> None:
    """Inserting into a nonexistent reading order returns 404."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    thread = await _make_thread(async_db, user_id=user.id, title="Test")
    await async_db.commit()

    response = await insert_client.post(
        "/api/v1/reading-orders/99999/items",
        json={"thread_id": thread.id, "position": 1},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_insert_item_nonexistent_thread(insert_client: AsyncClient, async_db: AsyncSession) -> None:
    """Inserting a nonexistent thread returns 404."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    order = await _make_reading_order(async_db, user_id=user.id, name="Order")
    await async_db.commit()

    response = await insert_client.post(
        f"/api/v1/reading-orders/{order.id}/items",
        json={"thread_id": 99999, "position": 1},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_insert_item_unauthenticated(async_db: AsyncSession) -> None:
    """Unauthenticated requests are rejected."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/reading-orders/1/items",
            json={"thread_id": 1, "position": 1},
        )
    assert response.status_code in (401, 403)
