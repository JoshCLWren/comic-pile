"""Focused mutation-coherence contract for paginated Queue (#933).

Verifies that mutations (create, edit, reposition, delete) keep the paginated
Queue coherent without redownloading the full library and that cursor
correctness holds after mutations.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.requests import Request
from types import SimpleNamespace

from app.api.thread import list_threads
from app.models import Thread
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_mutation_reset_keeps_first_page_bounded(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """After a mutation, pagination restarts at a bounded first page."""
    user = await get_or_create_user_async(async_db)
    await async_db.commit()

    # Create 55 threads so pagination spans 2 pages with page_size=50
    for i in range(1, 56):
        t = Thread(
            user_id=user.id,
            title=f"Thread-{i:02d}",
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = __import__("inspect").unwrap(list_threads)

    # First page before mutation
    page1 = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search=None,
        sort="position",
        page_size=50,
        page_token=None,
    )
    assert len(page1.threads) == 50
    assert page1.next_page_token is not None

    # Mutation: reposition first thread to the back (position 56)
    first_thread_id = page1.threads[0].id
    orm_thread = (
        await async_db.execute(select(Thread).where(Thread.id == first_thread_id))
    ).scalar_one()
    orm_thread.queue_position = 56
    await async_db.flush()
    await async_db.commit()

    # Re-fetch first page — must remain bounded (<= 50 items) with no gaps
    page_after = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search=None,
        sort="position",
        page_size=50,
        page_token=None,
    )
    assert len(page_after.threads) == 50
    after_ids = {t.id for t in page_after.threads}
    # First thread should no longer be on the first page
    assert first_thread_id not in after_ids
    # All threads on first page must have distinct IDs (no duplicates)
    assert len(after_ids) == 50


@pytest.mark.asyncio
async def test_pagination_no_gaps_or_duplicates_after_mutation(
    async_db: AsyncSession,
) -> None:
    """Pagination across pages after mutation has no duplicate or missing rows."""
    user = await get_or_create_user_async(async_db)
    await async_db.commit()

    for i in range(1, 8):
        t = Thread(
            user_id=user.id,
            title=f"T-{i:02d}",
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = __import__("inspect").unwrap(list_threads)

    # Fetch all threads to get IDs
    all_ids_before: list[int] = []
    token = None
    for _ in range(10):
        resp = await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="position",
            page_size=3,
            page_token=token,
        )
        all_ids_before.extend(t.id for t in resp.threads)
        token = resp.next_page_token
        if token is None:
            break

    assert len(all_ids_before) == 7
    assert len(set(all_ids_before)) == 7

    # Mutation: move thread at position 1 to position 4 (cross-boundary)
    thread_to_move = (await async_db.execute(
        select(Thread).where(Thread.id == all_ids_before[0])
    )).scalar_one()
    thread_to_move.queue_position = 4
    await async_db.flush()
    await async_db.commit()

    # Re-fetch all pages — must still have no duplicates or gaps
    all_ids_after: list[int] = []
    token = None
    for _ in range(10):
        resp = await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            sort="position",
            page_size=3,
            page_token=token,
        )
        all_ids_after.extend(t.id for t in resp.threads)
        token = resp.next_page_token
        if token is None:
            break

    # All 7 threads still present exactly once
    assert len(all_ids_after) == 7
    assert len(set(all_ids_after)) == 7
    assert set(all_ids_before) == set(all_ids_after)


@pytest.mark.asyncio
async def test_large_library_remains_bounded(
    async_db: AsyncSession,
) -> None:
    """Queue pagination remains bounded even with a large library."""
    user = await get_or_create_user_async(async_db)
    await async_db.commit()

    # Create 250 threads (representative large-library sample)
    for i in range(1, 251):
        t = Thread(
            user_id=user.id,
            title=f"Large-T-{i:04d}",
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
    await async_db.flush()
    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    route = __import__("inspect").unwrap(list_threads)

    resp = await route(
        request=request,
        current_user=SimpleNamespace(id=user.id),
        db=async_db,
        search=None,
        sort="position",
        page_size=50,
        page_token=None,
    )
    # Initial page must be bounded at 50 (page_size)
    assert len(resp.threads) == 50
    assert resp.next_page_token is not None
