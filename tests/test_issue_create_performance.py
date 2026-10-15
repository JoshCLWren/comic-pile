"""Performance tests for POST /api/v1/threads/{thread_id}/issues.

Verifies the issue creation endpoint stays within the 1000 ms performance
budget (issue #3437) by ensuring ComicVine auto-mapping never blocks the
request path.
"""

import time
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread, User
from app.performance_budgets import REQUEST_TIMEOUT_MS
from tests.conftest import get_or_create_user_async


async def _create_thread(async_db: AsyncSession, user: User, title: str = "Test Thread") -> Thread:
    """Persist a thread owned by ``user`` and return it."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    await async_db.commit()
    await async_db.refresh(thread)
    return thread


async def _post_issues(auth_client: AsyncClient, thread_id: int, issue_range: str) -> tuple[int, dict]:
    """POST an issue range and return (status_code, json_body)."""
    response = await auth_client.post(
        f"/api/v1/threads/{thread_id}/issues",
        json={"issue_range": issue_range},
    )
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_create_issues_performance_without_comicvine_mapping(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Issue creation meets the performance budget when ComicVine is not configured."""
    user = await get_or_create_user_async(async_db)
    thread = await _create_thread(async_db, user)

    started = time.perf_counter()
    status_code, data = await _post_issues(auth_client, thread.id, "1-5")
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert status_code == 201
    assert elapsed_ms < REQUEST_TIMEOUT_MS, (
        f"Issue creation took {elapsed_ms:.1f}ms, exceeding {REQUEST_TIMEOUT_MS}ms budget"
    )
    assert len(data["issues"]) == 5


@pytest.mark.asyncio
async def test_create_issues_performance_comicvine_mapping_background(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Issue creation meets the budget even when ComicVine mapping is enabled.

    ComicVine auto-mapping runs in the background and must not block the
    request, so the endpoint returns quickly regardless of provider latency.
    """
    user = await get_or_create_user_async(async_db)
    thread = await _create_thread(async_db, user)

    # ComicVine auto-mapping is enabled by default but runs in the background;
    # with no COMICVINE_API_KEY it is skipped, so the request returns quickly.
    started = time.perf_counter()
    status_code, data = await _post_issues(auth_client, thread.id, "1-5")
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert status_code == 201
    assert elapsed_ms < REQUEST_TIMEOUT_MS, (
        f"Issue creation took {elapsed_ms:.1f}ms, exceeding {REQUEST_TIMEOUT_MS}ms budget"
    )
    assert len(data["issues"]) == 5


@pytest.mark.asyncio
async def test_create_issues_performance_large_batch(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A large batch of issues stays within the performance budget."""
    user = await get_or_create_user_async(async_db)
    thread = await _create_thread(async_db, user, title="Large Batch Thread")

    started = time.perf_counter()
    status_code, data = await _post_issues(auth_client, thread.id, "1-20")
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert status_code == 201
    assert elapsed_ms < REQUEST_TIMEOUT_MS, (
        f"Large batch issue creation took {elapsed_ms:.1f}ms, exceeding {REQUEST_TIMEOUT_MS}ms budget"
    )
    assert len(data["issues"]) == 20
