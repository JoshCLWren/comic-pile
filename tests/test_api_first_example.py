"""Example tests demonstrating API-first testing pattern.

This file serves as a reference for the recommended testing approach that:
- Decouples tests from SQLAlchemy implementation details
- Uses API endpoints for test data setup
- Avoids MissingGreenlet errors
- Reflects real application usage
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread
from tests.conftest import create_thread_via_api, rate_thread_via_api, start_session_via_api


@pytest.mark.asyncio
async def test_create_and_rate_thread_api_first(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Example: Create thread and rate it using API-first pattern.

    This test demonstrates the recommended pattern:
    1. Use create_thread_via_api() instead of direct DB access
    2. Use start_session_via_api() to start a session via roll
    3. Use rate_thread_via_api() to rate the thread
    4. Use simple SELECT queries only for verification if needed

    Benefits:
    - No SQLAlchemy commit/refresh cycles to manage
    - No risk of MissingGreenlet errors
    - Cleaner, more readable test code
    - Tests reflect real user workflows
    """
    # Create thread via API (not direct DB access)
    thread = await create_thread_via_api(
        auth_client, title="Spider-Man", format="Comic", issues_remaining=10
    )
    assert thread["title"] == "Spider-Man"
    assert thread["issues_remaining"] == 10

    # Start session via roll (creates session and rolls)
    roll_data = await start_session_via_api(auth_client, start_die=10)
    assert "title" in roll_data

    # Rate the thread via API
    rate_data = await rate_thread_via_api(auth_client, rating=4.5, issues_read=2)
    assert rate_data["issues_remaining"] == 8  # 10 - 2 = 8
    assert rate_data["last_rating"] == 4.5

    # Optional: Verify final state with simple SELECT query
    result = await async_db.execute(select(Thread).where(Thread.title == "Spider-Man"))
    db_thread = result.scalar_one_or_none()
    assert db_thread is not None
    assert db_thread.issues_remaining == 8
    assert db_thread.last_rating == 4.5


@pytest.mark.asyncio
async def test_multiple_threads_api_first(auth_client: AsyncClient) -> None:
    """Example: Create multiple threads using API-first pattern.

    Demonstrates parallel creation without worrying about SQLAlchemy sessions.
    """
    # Create multiple threads via API
    thread1 = await create_thread_via_api(
        auth_client, title="Superman", format="Comic", issues_remaining=5
    )
    thread2 = await create_thread_via_api(
        auth_client, title="Batman", format="Comic", issues_remaining=10
    )
    thread3 = await create_thread_via_api(
        auth_client, title="Wonder Woman", format="Comic", issues_remaining=8
    )

    # Verify via API endpoint (not direct DB access)
    response = await auth_client.get("/api/threads/")
    assert response.status_code == 200

    threads = response.json()
    assert len(threads) == 3
    assert threads[0]["title"] == "Superman"
    assert threads[1]["title"] == "Batman"
    assert threads[2]["title"] == "Wonder Woman"


@pytest.mark.asyncio
async def test_old_pattern_for_comparison(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Counter-example: Old pattern (NOT recommended).

    This demonstrates the old pattern that is tightly coupled to SQLAlchemy.
    DO NOT use this pattern for new tests.

    Problems with this pattern:
    - Requires understanding SQLAlchemy session management
    - Multiple commit/refresh cycles prone to errors
    - Risk of MissingGreenlet when accessing model attributes after commit
    - Doesn't reflect real application usage
    - More code, harder to maintain
    """
    from datetime import UTC, datetime

    from tests.conftest import get_or_create_user_async
    from app.models import Event, Session as SessionModel

    # ❌ Direct DB access - requires understanding SQLAlchemy
    user = await get_or_create_user_async(async_db)

    # ❌ Multiple commit/refresh cycles
    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)  # MissingGreenlet risk

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)  # MissingGreenlet risk

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
        timestamp=datetime.now(UTC),
    )
    async_db.add(event)
    await async_db.commit()

    # Finally test the endpoint
    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    # This is the ONLY line that actually tests the endpoint
    # All the code above is just setup!
