"""Batch-enrichment coverage for reading-order item responses (issue #2612)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

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
from app.models.issue import Issue
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.models.user import User


@pytest_asyncio.fixture
async def batch_client(async_db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Authenticated HTTP client that uses the provided async_db session."""
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


@pytest.mark.asyncio
async def test_thread_reading_orders_enriches_many_items(
    batch_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Multi-item orders resolve titles and read flags without per-item selects."""
    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    thread_a = await _make_thread(async_db, user_id=user.id, title="Alpha")
    thread_b = await _make_thread(async_db, user_id=user.id, title="Beta")
    thread_c = await _make_thread(async_db, user_id=user.id, title="Gamma")

    order_one = ReadingOrder(name="First", user_id=user.id)
    order_two = ReadingOrder(name="Second", user_id=user.id)
    async_db.add(order_one)
    async_db.add(order_two)
    await async_db.flush()

    async_db.add(
        ReadingOrderItem(
            reading_order_id=order_one.id,
            thread_id=thread_a.id,
            position=1,
            issue_number="1",
        )
    )
    async_db.add(
        ReadingOrderItem(
            reading_order_id=order_one.id,
            thread_id=thread_b.id,
            position=2,
            issue_number="1",
        )
    )
    async_db.add(
        ReadingOrderItem(
            reading_order_id=order_one.id,
            thread_id=thread_c.id,
            position=3,
            issue_number=None,
        )
    )
    async_db.add(
        ReadingOrderItem(
            reading_order_id=order_two.id,
            thread_id=thread_a.id,
            position=1,
            issue_number="2",
        )
    )
    async_db.add(
        ReadingOrderItem(
            reading_order_id=order_two.id,
            thread_id=thread_c.id,
            position=2,
            issue_number="1",
        )
    )
    async_db.add(
        Issue(
            thread_id=thread_a.id,
            issue_number="1",
            position=1,
            status="read",
            read_at=datetime.now(UTC),
        )
    )
    async_db.add(
        Issue(
            thread_id=thread_b.id,
            issue_number="1",
            position=1,
            status="unread",
        )
    )
    async_db.add(
        Issue(
            thread_id=thread_c.id,
            issue_number="1",
            position=1,
            status="read",
            read_at=datetime.now(UTC),
        )
    )
    await async_db.commit()

    response = await batch_client.get(f"/api/v1/threads/{thread_a.id}/reading-orders")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["reading_orders"]) == 2

    by_name = {order["name"]: order for order in body["reading_orders"]}

    first = by_name["First"]
    assert first["total_items"] == 3
    assert first["completed_items"] == 1
    first_items = {item["thread_title"]: item for item in first["items"]}
    assert [item["thread_title"] for item in first["items"]] == [
        "Alpha",
        "Beta",
        "Gamma",
    ]
    assert first_items["Alpha"]["is_read"] is True
    assert first_items["Alpha"]["issue_number"] == "1"
    assert first_items["Beta"]["is_read"] is False
    assert first_items["Gamma"]["is_read"] is False
    assert first_items["Gamma"]["issue_number"] is None

    second = by_name["Second"]
    assert second["total_items"] == 2
    assert second["completed_items"] == 1
    second_items = {item["thread_title"]: item for item in second["items"]}
    assert second_items["Alpha"]["is_read"] is False
    assert second_items["Alpha"]["issue_number"] == "2"
    assert second_items["Gamma"]["is_read"] is True


@pytest.mark.asyncio
async def test_insert_reports_sql_count_for_multi_item_order(
    batch_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Inserting into a multi-item order reports the SQL-counted total."""
    user = (await async_db.execute(select(User).limit(1))).scalar_one()
    threads = [await _make_thread(async_db, user_id=user.id, title=f"T{i}") for i in range(4)]
    order = ReadingOrder(name="Counted", user_id=user.id)
    async_db.add(order)
    await async_db.flush()
    for i, thread in enumerate(threads[:3], start=1):
        async_db.add(
            ReadingOrderItem(
                reading_order_id=order.id, thread_id=thread.id, position=i
            )
        )
    await async_db.commit()

    response = await batch_client.post(
        f"/api/v1/reading-orders/{order.id}/items",
        json={"thread_id": threads[3].id, "position": 2},
    )
    assert response.status_code == 201, response.text
    assert response.json()["total_items"] == 4
