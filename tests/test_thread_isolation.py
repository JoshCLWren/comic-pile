"""Tests for thread scoping isolation across users."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from httpx import AsyncClient
from app.auth import create_access_token, hash_password
from app.models import Thread, User
from app.services.thread_service import list_queue_threads

PASSWORD_HASH = hash_password("password")


@pytest_asyncio.fixture(scope="function")
async def user_a(async_db: AsyncSession) -> User:
    """Create user A for testing."""
    user = User(username="test_user_a", password_hash=PASSWORD_HASH, created_at=None)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def user_b(async_db: AsyncSession) -> User:
    """Create user B for testing."""
    user = User(username="test_user_b", password_hash=PASSWORD_HASH, created_at=None)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def user_a_thread(async_db: AsyncSession, user_a: User) -> Thread:
    """Create a thread for user A."""
    thread = Thread(
        title="User A Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=user_a.id,
        status="active",
        created_at=None,
    )
    async_db.add(thread)
    await async_db.flush()
    await async_db.refresh(thread)
    return thread


@pytest_asyncio.fixture(scope="function")
async def user_b_thread(async_db: AsyncSession, user_b: User) -> Thread:
    """Create a thread for user B."""
    thread = Thread(
        title="User B Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        user_id=user_b.id,
        status="active",
        created_at=None,
    )
    async_db.add(thread)
    await async_db.flush()
    await async_db.refresh(thread)
    return thread


@pytest.mark.asyncio
async def test_thread_scoped_by_user_on_list(
    async_db: AsyncSession,
    user_a: User,
    user_b: User,
    user_a_thread: Thread,
    user_b_thread: Thread,
) -> None:
    """The Queue collection only returns the requesting reader's threads."""
    _ = user_a_thread
    _ = user_b_thread
    page_a = await list_queue_threads(
        async_db, user_a.id, search=None, sort="position", page_size=50, page_token=None
    )
    assert len(page_a.threads) == 1
    assert page_a.threads[0].title == "User A Thread"

    page_b = await list_queue_threads(
        async_db, user_b.id, search=None, sort="position", page_size=50, page_token=None
    )
    assert len(page_b.threads) == 1
    assert page_b.threads[0].title == "User B Thread"


