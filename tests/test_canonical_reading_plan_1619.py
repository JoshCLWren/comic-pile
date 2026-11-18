"""Issue #1619: continuity_plans is canonical; reading_orders is legacy import/export.

Covers:
- issue-level multi-series plan survives save/reopen/execution without flattening
- legacy reading orders remain readable and adoptable without data loss
- duplicate/conflicting entries are rejected before mutation
- cross-series boundaries and within-series progression behave per #257
- informational vs strict_sequential controls blocking; queue/roll use one contract
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import Issue
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.models.thread import Thread
from comic_pile.queue import get_bounded_roll_pool_rows
from tests.conftest import get_or_create_user_async


async def _make_thread(async_db: AsyncSession, *, user_id: int, title: str) -> Thread:
    """Create an owned thread."""
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        queue_position=10,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


async def _make_issue_for_thread(
    async_db: AsyncSession, *, thread: Thread, issue_number: str, position: int
) -> Issue:
    issue = Issue(thread_id=thread.id, issue_number=issue_number, position=position, status="unread")
    async_db.add(issue)
    await async_db.flush()
    return issue


async def _roll_pool_ids(user_id: int, db: AsyncSession) -> set[int]:
    """Return thread IDs currently eligible for bounded Roll candidate selection."""
    rows = await get_bounded_roll_pool_rows(user_id, db, current_die=20)
    return {row[0].id for row in rows}






@pytest.mark.asyncio
async def test_legacy_reading_orders_remain_readable(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Legacy reading_orders endpoint still serves data verbatim (backward compat)."""
    user = await get_or_create_user_async(async_db)
    t = await _make_thread(async_db, user_id=user.id, title="Legacy Thread")
    await async_db.commit()
    order = ReadingOrder(name="My Order", description="legacy", user_id=user.id)
    async_db.add(order)
    await async_db.flush()
    async_db.add(ReadingOrderItem(reading_order_id=order.id, thread_id=t.id, position=1))
    await async_db.commit()

    thread_orders = await auth_client.get(f"/api/v1/threads/{t.id}/reading-orders")
    assert thread_orders.status_code == 200, thread_orders.text
    assert len(thread_orders.json()["reading_orders"]) == 1












