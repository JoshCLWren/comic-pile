"""API endpoint integration tests."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReadingSession, Thread, User
from app.services import thread_service
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_list_threads(
    async_db: AsyncSession, default_user: User, sample_data: dict
) -> None:
    """The Queue collection projection returns active threads only (#2567)."""
    _ = sample_data
    page = await thread_service.list_queue_threads(
        async_db, default_user.id, search=None, sort="position", page_size=50, page_token=None
    )

    threads = page.threads
    assert len(threads) == 4
    assert threads[0].title == "Superman"
    assert threads[1].title == "Batman"
    assert threads[2].title == "Flash"
    assert threads[3].title == "Aquaman"
    assert all(thread.status == "active" for thread in threads)


@pytest.mark.asyncio
async def test_list_threads_search(
    async_db: AsyncSession, default_user: User, sample_data: dict
) -> None:
    """Queue search filters active threads by title (#2567)."""
    _ = sample_data

    page = await thread_service.list_queue_threads(
        async_db, default_user.id, search="man", sort="position", page_size=50, page_token=None
    )
    titles = {thread.title for thread in page.threads}
    # Wonder Woman is completed, so it must not leak into active Queue search.
    assert titles == {"Superman", "Batman", "Aquaman"}


@pytest.mark.asyncio
async def test_list_threads_empty(async_db: AsyncSession) -> None:
    """An empty Queue collection returns no rows and no cursor."""
    user = await get_or_create_user_async(async_db, username="empty_queue_reader")
    page = await thread_service.list_queue_threads(
        async_db, user.id, search=None, sort="position", page_size=50, page_token=None
    )
    assert page.threads == []
    assert page.next_page_token is None
    assert page.active_count == 0


