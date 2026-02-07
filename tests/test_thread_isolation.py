"""Tests for thread scoping isolation across users."""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


from httpx import AsyncClient
from app.models import Thread, User


@pytest_asyncio.fixture(scope="function")
async def user_a(async_db: AsyncSession) -> User:
    """Create user A for testing."""
    from app.auth import hash_password

    user = User(username="test_user_a", password_hash=hash_password("password"), created_at=None)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def user_b(async_db: AsyncSession) -> User:
    """Create user B for testing."""
    from app.auth import hash_password

    user = User(username="test_user_b", password_hash=hash_password("password"), created_at=None)
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
async def test_thread_scoped_by_user_on_list(client: AsyncClient, user_a: User, user_b: User, user_a_thread: Thread, user_b_thread: Thread) -> None:
    """Test list threads only returns threads for authenticated user."""
    _ = user_a
    _ = user_b
    _ = user_a_thread
    _ = user_b_thread
    login_a = await client.post(
        "/api/auth/login", json={"username": "test_user_a", "password": "password"}
    )
    assert login_a.status_code == 200
    token_a = login_a.json()["access_token"]

    response = await client.get("/api/threads/", headers={"Authorization": f"Bearer {token_a}"})
    assert response.status_code == 200
    threads = response.json()
    assert len(threads) == 1
    assert threads[0]["title"] == "User A Thread"

    login_b = await client.post(
        "/api/auth/login", json={"username": "test_user_b", "password": "password"}
    )
    assert login_b.status_code == 200
    token_b = login_b.json()["access_token"]

    response = await client.get("/api/threads/", headers={"Authorization": f"Bearer {token_b}"})
    assert response.status_code == 200
    threads = response.json()
    assert len(threads) == 1
    assert threads[0]["title"] == "User B Thread"


@pytest.mark.asyncio
async def test_thread_get_returns_404_for_other_users_thread(client: AsyncClient, user_a: User, user_b: User, user_a_thread: Thread, user_b_thread: Thread) -> None:
    """Test GET /api/threads/{id} returns 404 for other users' threads."""
    _ = user_a
    _ = user_b
    login_a = await client.post(
        "/api/auth/login", json={"username": "test_user_a", "password": "password"}
    )
    assert login_a.status_code == 200
    token_a = login_a.json()["access_token"]

    response = await client.get(
        f"/api/threads/{user_b_thread.id}", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert response.status_code == 404

    login_b = await client.post(
        "/api/auth/login", json={"username": "test_user_b", "password": "password"}
    )
    assert login_b.status_code == 200
    token_b = login_b.json()["access_token"]

    response = await client.get(
        f"/api/threads/{user_a_thread.id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_thread_update_fails_for_other_users_thread(client: AsyncClient, async_db: AsyncSession, user_a: User, user_b: User, user_b_thread: Thread) -> None:
    """Test PUT /api/threads/{id} fails for other users' threads."""
    _ = user_a
    _ = user_b
    login_a = await client.post(
        "/api/auth/login", json={"username": "test_user_a", "password": "password"}
    )
    assert login_a.status_code == 200
    token_a = login_a.json()["access_token"]

    response = await client.put(
        f"/api/threads/{user_b_thread.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Hacked Title"},
    )
    assert response.status_code == 404

    login_b = await client.post(
        "/api/auth/login", json={"username": "test_user_b", "password": "password"}
    )
    assert login_b.status_code == 200
    token_b = login_b.json()["access_token"]

    response = await client.put(
        f"/api/threads/{user_b_thread.id}",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"title": "Valid Update"},
    )
    assert response.status_code == 200

    await async_db.refresh(user_b_thread)
    assert user_b_thread.title == "Valid Update"


@pytest.mark.asyncio
async def test_thread_delete_fails_for_other_users_thread(client: AsyncClient, async_db: AsyncSession, user_a: User, user_b: User, user_b_thread: Thread) -> None:
    """Test DELETE /api/threads/{id} fails for other users' threads."""
    _ = user_a
    _ = user_b
    login_a = await client.post(
        "/api/auth/login", json={"username": "test_user_a", "password": "password"}
    )
    assert login_a.status_code == 200
    token_a = login_a.json()["access_token"]

    response = await client.delete(
        f"/api/threads/{user_b_thread.id}", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert response.status_code == 404

    thread_exists_result = await async_db.execute(
        select(Thread).where(Thread.id == user_b_thread.id)
    )
    thread_exists = thread_exists_result.scalar_one_or_none()
    assert thread_exists is not None

    login_b = await client.post(
        "/api/auth/login", json={"username": "test_user_b", "password": "password"}
    )
    assert login_b.status_code == 200
    token_b = login_b.json()["access_token"]

    response = await client.delete(
        f"/api/threads/{user_b_thread.id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.status_code == 204

    thread_exists_result = await async_db.execute(
        select(Thread).where(Thread.id == user_b_thread.id)
    )
    thread_exists = thread_exists_result.scalar_one_or_none()
    assert thread_exists is None


@pytest.mark.asyncio
async def test_thread_creation_sets_user_id(client: AsyncClient, async_db: AsyncSession, user_a: User, user_b: User) -> None:
    """Test POST /api/threads/ sets user_id from authenticated user."""
    login_a = await client.post(
        "/api/auth/login", json={"username": "test_user_a", "password": "password"}
    )
    assert login_a.status_code == 200
    token_a = login_a.json()["access_token"]

    response = await client.post(
        "/api/threads/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "User A Thread", "format": "Comic", "issues_remaining": 10},
    )
    assert response.status_code == 201
    thread_data = response.json()
    assert thread_data["title"] == "User A Thread"

    login_b = await client.post(
        "/api/auth/login", json={"username": "test_user_b", "password": "password"}
    )
    assert login_b.status_code == 200
    token_b = login_b.json()["access_token"]

    response = await client.post(
        "/api/threads/",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"title": "User B Thread", "format": "Comic", "issues_remaining": 5},
    )
    assert response.status_code == 201
    thread_data = response.json()
    assert thread_data["title"] == "User B Thread"

    result = await async_db.execute(select(Thread))
    all_threads = result.scalars().all()
    assert len(all_threads) == 2
    for thread in all_threads:
        assert thread.user_id in (user_a.id, user_b.id)
