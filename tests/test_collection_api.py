"""Tests for Collection API endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Collection, Thread


@pytest.fixture
async def sample_collection(auth_client: AsyncClient, async_db: AsyncSession) -> Collection:
    """Create a sample collection for testing."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    collection = Collection(
        name="DC Comics",
        user_id=user.id,
        is_default=False,
        position=0,
    )
    async_db.add(collection)
    await async_db.commit()
    await async_db.refresh(collection)

    return collection


@pytest.fixture
async def sample_thread(auth_client: AsyncClient, async_db: AsyncSession) -> Thread:
    """Create a sample thread for testing."""
    from datetime import UTC, datetime
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    return thread


@pytest.mark.asyncio
async def test_create_collection(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Test creating a collection."""
    response = await auth_client.post(
        "/api/v1/collections/", json={"name": "DC Comics", "is_default": False, "position": 0}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "DC Comics"
    assert data["user_id"] == 1


@pytest.mark.asyncio
async def test_list_collections(auth_client: AsyncClient) -> None:
    """Test listing collections."""
    response = await auth_client.get("/api/v1/collections/")
    assert response.status_code == 200
    data = response.json()
    assert "collections" in data
    assert isinstance(data["collections"], list)


@pytest.mark.asyncio
async def test_move_thread_to_collection(
    auth_client: AsyncClient,
    sample_thread: Thread,
    sample_collection: Collection,
    async_db: AsyncSession,
) -> None:
    """Test moving a thread to a collection."""
    response = await auth_client.post(
        f"/api/threads/{sample_thread.id}:moveToCollection",
        params={"collection_id": sample_collection.id},
    )
    assert response.status_code == 200

    await async_db.refresh(sample_thread)
    assert sample_thread.collection_id == sample_collection.id


@pytest.mark.asyncio
async def test_filter_threads_by_collection(
    auth_client: AsyncClient,
    sample_thread: Thread,
    sample_collection: Collection,
    async_db: AsyncSession,
) -> None:
    """Test filtering threads by collection."""
    # Move thread to collection
    sample_thread.collection_id = sample_collection.id
    await async_db.commit()

    # Filter by collection
    response = await auth_client.get(
        "/api/threads/", params={"collection_id": sample_collection.id}
    )
    assert response.status_code == 200
    threads = response.json()
    assert len(threads) == 1
    assert threads[0]["id"] == sample_thread.id
