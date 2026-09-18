"""Authoritative whole-queue metadata behind issue #2568.

The Queue is cursor-paginated, so a loaded page is only ever a prefix of the
queue. Every count, validation bound, and repositioning decision that needs
whole-queue knowledge must come from authoritative metadata, never from the
number of threads currently loaded in the browser.

This module proves four contracts:

- ``QueueThreadListResponse.active_count`` is the total active queue size, not
  the loaded page size, independent of search filters and sort order.
- Completed threads do not inflate ``active_count``.
- Repositioning to a valid target beyond the first loaded page is accepted and
  lands correctly (the browser must not reject targets past its loaded slice).
- Out-of-range targets (below 1 or above the authoritative total) are rejected
  against the whole-queue bound.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from inspect import unwrap
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.thread import list_threads
from app.models import Thread
from app.schemas import QueueThreadListResponse
from comic_pile.queue import move_to_position
from tests.conftest import get_or_create_user_async

PAGE_SIZE = 50
QUEUE_SIZE = 120  # substantially larger than one page


def _make_request() -> Request:
    """Build a minimal Starlette request matching ``list_threads``."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )


async def _seed_active_queue(db: AsyncSession, user_id: int, count: int) -> None:
    """Insert ``count`` active threads with deterministic titles and positions.

    Args:
        db: Async database session.
        user_id: Owning user for every seeded thread.
        count: Number of active threads to insert.
    """
    now = datetime.now(UTC)
    await db.execute(
        insert(Thread),
        [
            {
                "user_id": user_id,
                "title": f"Queue Thread {i:05d}",
                "format": "Comic",
                "issues_remaining": 3,
                "queue_position": i,
                "status": "active",
                "created_at": now - timedelta(minutes=count - i),
            }
            for i in range(1, count + 1)
        ],
    )
    await db.commit()


async def _fetch_first_page(db: AsyncSession, user_id: int) -> QueueThreadListResponse:
    """Call the unwrapped ``list_threads`` route exactly as the API would.

    Args:
        db: Async database session.
        user_id: Authenticated user id for the request.

    Returns:
        The first page of the Queue response (50 rows).
    """
    route = unwrap(list_threads)
    return await route(
        request=_make_request(),
        current_user=SimpleNamespace(id=user_id),
        db=db,
        search=None,
        sort="position",
        page_size=PAGE_SIZE,
        page_token=None,
    )


@pytest.mark.asyncio
async def test_active_count_is_whole_queue_total_not_loaded_page(
    async_db: AsyncSession,
) -> None:
    """First page of a 120-thread queue reports 50 rows and 120 active."""
    user = await get_or_create_user_async(async_db)
    await _seed_active_queue(async_db, user.id, QUEUE_SIZE)

    page = await _fetch_first_page(async_db, user.id)

    assert len(page.threads) == PAGE_SIZE
    assert page.next_page_token is not None
    assert page.active_count == QUEUE_SIZE


@pytest.mark.asyncio
async def test_active_count_is_independent_of_search_and_sort(
    async_db: AsyncSession,
) -> None:
    """active_count ignores search filters that shrink the loaded rows."""
    user = await get_or_create_user_async(async_db)
    await _seed_active_queue(async_db, user.id, QUEUE_SIZE)

    route = unwrap(list_threads)
    searched = await route(
        request=_make_request(),
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search="Queue Thread 00001",
        sort="position",
        page_size=PAGE_SIZE,
        page_token=None,
    )

    assert len(searched.threads) == 1
    assert searched.active_count == QUEUE_SIZE


@pytest.mark.asyncio
async def test_active_count_excludes_completed_threads(
    async_db: AsyncSession,
) -> None:
    """Completed threads outside the active queue do not inflate active_count."""
    user = await get_or_create_user_async(async_db)
    await _seed_active_queue(async_db, user.id, 5)

    completed = Thread(
        user_id=user.id,
        title="Finished Series",
        format="Comic",
        issues_remaining=0,
        queue_position=99,
        status="completed",
        created_at=datetime.now(UTC),
    )
    async_db.add(completed)
    await async_db.commit()

    page = await _fetch_first_page(async_db, user.id)
    assert page.active_count == 5


@pytest.mark.asyncio
async def test_reposition_beyond_loaded_page_uses_authoritative_bound(
    async_db: AsyncSession,
) -> None:
    """A target beyond the first loaded page is valid and lands correctly."""
    user = await get_or_create_user_async(async_db)
    await _seed_active_queue(async_db, user.id, QUEUE_SIZE)

    page = await _fetch_first_page(async_db, user.id)
    assert len(page.threads) == PAGE_SIZE
    assert page.active_count == QUEUE_SIZE

    moved_thread_id = page.threads[4].id
    changes = await move_to_position(moved_thread_id, user.id, QUEUE_SIZE, async_db)
    assert moved_thread_id in changes

    result = await async_db.execute(
        select(Thread.id)
        .where(Thread.user_id == user.id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position, Thread.id)
    )
    ordered_ids = [row[0] for row in result.fetchall()]
    assert len(ordered_ids) == QUEUE_SIZE
    assert ordered_ids.index(moved_thread_id) == QUEUE_SIZE - 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "message"),
    [
        (0, "Position must be at least 1"),
        (QUEUE_SIZE + 1, "out of range"),
    ],
)
async def test_position_validation_uses_authoritative_queue_bounds(
    target: int,
    message: str,
    async_db: AsyncSession,
) -> None:
    """Out-of-range reposition targets are rejected against the whole queue."""
    user = await get_or_create_user_async(async_db)
    await _seed_active_queue(async_db, user.id, QUEUE_SIZE)

    page = await _fetch_first_page(async_db, user.id)
    moved_thread_id = page.threads[0].id

    with pytest.raises(ValueError, match=message):
        await move_to_position(moved_thread_id, user.id, target, async_db)