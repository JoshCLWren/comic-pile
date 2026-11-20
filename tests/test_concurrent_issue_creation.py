"""Tests for concurrent issue creation to verify row-level locking."""

import asyncio
import pytest
from datetime import UTC, datetime
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.models import Issue, Thread, User
from tests.conftest import get_or_create_user_async, get_test_database_url


@pytest.mark.asyncio
async def test_concurrent_issue_adds_no_position_collisions(
    async_db_committed: AsyncSession,
) -> None:
    """Test that concurrent requests to add issues don't create duplicate positions.

    This is a CRITICAL test for production readiness. It verifies that row-level
    locking (SELECT FOR UPDATE) prevents race conditions when multiple requests
    add issues to the same thread simultaneously.

    Without proper locking, concurrent requests would:
    1. Read the same max_position
    2. Calculate the same offset
    3. Create issues with duplicate positions

    With SELECT FOR UPDATE locking, requests are serialized and positions are unique.

    Test strategy:
    - Create a thread with no initial issues
    - Launch 20 concurrent requests, each adding 5 issues (100 total expected)
    - Each request adds a different range to avoid duplicate issue_numbers
    - Verify all 100 issues were created
    - Verify all positions are unique (no collisions)
    - Verify positions are sequential (1-100)
    """
    from app.main import app
    from app.database import get_db
    from app.auth import get_current_user
    from collections.abc import AsyncGenerator

    user = await get_or_create_user_async(async_db_committed)

    thread = Thread(
        title="Concurrent Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db_committed.add(thread)
    await async_db_committed.commit()
    await async_db_committed.refresh(thread)
    thread_id = thread.id

    database_url = get_test_database_url()
    override_engine = create_async_engine(database_url, echo=False, pool_size=20, max_overflow=0)
    override_session_maker = async_sessionmaker(
        bind=override_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def add_issues(range_start: int) -> dict:
        """Add issues concurrently using a dedicated client per request."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            csrf_token = generate_csrf_token()
            client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
            response = await client.post(
                f"/api/v1/threads/{thread_id}/issues",
                json={"issue_range": f"{range_start}-{range_start + 4}"},
                headers={CSRF_HEADER_NAME: csrf_token},
            )

        assert response.status_code == 201, f"Failed for range {range_start}: {response.text}"
        return response.json()

    # Set overrides before all concurrent requests
    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        async with override_session_maker() as session:
            yield session

    async def override_get_current_user() -> User:
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    try:
        # Launch 20 concurrent requests: 1-5, 6-10, 11-15, ..., 96-100
        # Each adds 5 issues, so we expect 100 total issues
        ranges = list(range(1, 100, 5))
        tasks = [add_issues(start) for start in ranges]

        # Run all requests concurrently
        results = await asyncio.gather(*tasks)
    finally:
        # Clear overrides ONCE after all requests complete
        app.dependency_overrides.clear()
        await override_engine.dispose()

    # Count total issues created across all responses
    total_created = sum(len(r["issues"]) for r in results)
    assert total_created == 100, f"Expected 100 issues, got {total_created}"

    # Verify database has exactly 100 issues
    count_result = await async_db_committed.execute(
        select(func.count()).select_from(Issue).where(Issue.thread_id == thread.id)
    )
    total_count = count_result.scalar()
    assert total_count == 100, f"Database has {total_count} issues, expected 100"

    # Verify all positions are unique
    positions_result = await async_db_committed.execute(
        select(Issue.position).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    positions = [row[0] for row in positions_result.fetchall()]

    # Check no duplicates
    assert len(positions) == len(set(positions)), f"Found duplicate positions: {positions}"

    # Check positions are sequential from 1 to 100
    assert positions == list(range(1, 101)), f"Positions not sequential: {positions}"

    # Verify all issue_numbers are unique
    issue_numbers_result = await async_db_committed.execute(
        select(Issue.issue_number).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issue_numbers = [row[0] for row in issue_numbers_result.fetchall()]

    assert len(issue_numbers) == len(set(issue_numbers)), (
        f"Found duplicate issue_numbers: {issue_numbers}"
    )

    # Verify thread metadata was updated correctly
    await async_db_committed.refresh(thread)
    assert thread.total_issues == 100, f"Thread total_issues is {thread.total_issues}, expected 100"
    assert thread.issues_remaining == 100, (
        f"Thread issues_remaining is {thread.issues_remaining}, expected 100"
    )


@pytest.mark.asyncio
async def test_concurrent_issue_adds_same_thread_different_overlaps(
    async_db_committed: AsyncSession,
) -> None:
    """Test concurrent adds with overlapping ranges don't cause issues.

    This tests that the locking works correctly even when requests add issues
    that would have overlapping positions if they weren't serialized.
    """
    from app.main import app
    from app.database import get_db
    from app.auth import get_current_user
    from collections.abc import AsyncGenerator

    user = await get_or_create_user_async(async_db_committed)

    thread = Thread(
        title="Overlap Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db_committed.add(thread)
    await async_db_committed.commit()
    await async_db_committed.refresh(thread)
    thread_id = thread.id

    database_url = get_test_database_url()
    override_engine = create_async_engine(database_url, echo=False, pool_size=10, max_overflow=0)
    override_session_maker = async_sessionmaker(
        bind=override_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def add_issues(range_str: str) -> dict:
        """Add issues concurrently."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            csrf_token = generate_csrf_token()
            client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
            response = await client.post(
                f"/api/v1/threads/{thread_id}/issues",
                json={"issue_range": range_str},
                headers={CSRF_HEADER_NAME: csrf_token},
            )

            assert response.status_code in (201, 400, 409), (
                f"Unexpected status {response.status_code}: {response.text}"
            )
            if response.status_code in (400, 409):
                detail = response.json().get("detail", "")
                assert "already exist" in detail.lower(), (
                    f"Unexpected {response.status_code} error: {detail}"
                )
                return {"issues": []}
            return response.json()

    # Set overrides before all concurrent requests
    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        async with override_session_maker() as session:
            yield session

    async def override_get_current_user() -> User:
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    try:
        # Launch 10 concurrent requests with different ranges
        # Total unique issue numbers: 1-50
        ranges = [
            "1-10",
            "11-20",
            "21-30",
            "31-40",
            "41-50",
            "1-5",
            "6-15",
            "16-25",
            "26-35",
            "36-45",
        ]
        tasks = [add_issues(r) for r in ranges]

        results = await asyncio.gather(*tasks)
    finally:
        # Clear overrides ONCE after all requests complete
        app.dependency_overrides.clear()
        await override_engine.dispose()

    # Count unique issues created
    created_issues = set()
    for result in results:
        if result:
            for issue in result["issues"]:
                created_issues.add(issue["issue_number"])

    # Should have exactly 50 unique issues
    assert len(created_issues) == 50, f"Expected 50 unique issues, got {len(created_issues)}"

    # Verify database has exactly 50 issues
    count_result = await async_db_committed.execute(
        select(func.count()).select_from(Issue).where(Issue.thread_id == thread.id)
    )
    total_count = count_result.scalar()
    assert total_count == 50, f"Database has {total_count} issues, expected 50"

    # Verify all positions are unique
    positions_result = await async_db_committed.execute(
        select(Issue.position).where(Issue.thread_id == thread.id)
    )
    positions = [row[0] for row in positions_result.fetchall()]

    assert len(positions) == len(set(positions)), f"Found duplicate positions: {positions}"
