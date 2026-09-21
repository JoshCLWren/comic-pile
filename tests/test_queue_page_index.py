"""Tests for the queue page index and query plan.

Verifies that fetch_queue_page uses the user-scoped partial index
instead of the global queue_position index.
"""

import pytest
from datetime import UTC, datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread, User


@pytest.mark.asyncio
async def test_queue_page_uses_user_scoped_index(async_db_committed: AsyncSession):
    """Verify the queue page query uses the partial index for active threads."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db_committed.add(user)
    await async_db_committed.flush()

    other_user = User(username="other_user", created_at=datetime.now(UTC))
    async_db_committed.add(other_user)
    await async_db_committed.flush()

    # Create many threads for other_user to simulate a large account
    other_threads = [
        Thread(
            user_id=other_user.id,
            title=f"Other Thread {i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        for i in range(1, 1000)
    ]
    async_db_committed.add_all(other_threads)

    # Create threads for the test user
    test_threads = [
        Thread(
            user_id=user.id,
            title=f"Test Thread {i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            created_at=datetime.now(UTC),
        )
        for i in range(1, 51)
    ]
    async_db_committed.add_all(test_threads)

    # Add some completed threads for the test user
    completed_threads = [
        Thread(
            user_id=user.id,
            title=f"Completed Thread {i}",
            format="Comic",
            issues_remaining=0,
            queue_position=i + 100,
            status="completed",
            created_at=datetime.now(UTC),
        )
        for i in range(1, 11)
    ]
    async_db_committed.add_all(completed_threads)

    await async_db_committed.commit()

    # Update statistics for the planner
    await async_db_committed.execute(text("ANALYZE threads"))

    # Disable sequential scans to force index usage
    await async_db_committed.execute(text("SET LOCAL enable_seqscan = off"))
    await async_db_committed.execute(text("SET LOCAL enable_bitmapscan = off"))

    # Query pattern from fetch_queue_page for "position" sort:
    # WHERE user_id = $1 AND status = 'active'
    # ORDER BY is_blocked ASC, queue_position ASC, id ASC
    # LIMIT 50
    explain_query = text("""
        EXPLAIN (ANALYZE, FORMAT JSON)
        SELECT * FROM threads
        WHERE user_id = :user_id
        AND status = 'active'
        ORDER BY is_blocked ASC, queue_position ASC, id ASC
        LIMIT 50
    """)

    result = await async_db_committed.execute(explain_query, {"user_id": user.id})
    plan = result.scalar()
    assert plan is not None, "EXPLAIN query should return a plan"

    # SQLAlchemy with asyncpg already deserializes JSON
    plan_data = plan if isinstance(plan, list) else [plan]

    def collect_index_names(node: dict) -> set[str]:
        """Recursively collect index names referenced in a query plan."""
        index_names = set()
        index_name = node.get("Index Name")
        if isinstance(index_name, str):
            index_names.add(index_name)
        for child in node.get("Plans", []):
            index_names.update(collect_index_names(child))
        return index_names

    plan_nodes = plan_data[0]["Plan"]
    used_indexes = collect_index_names(plan_nodes)

    # The query should use the partial index for active threads,
    # NOT the global ix_thread_position index
    assert "ix_thread_user_active_queue_position" in used_indexes, (
        f"Plan did not reference ix_thread_user_active_queue_position. "
        f"Used indexes: {used_indexes}"
    )
    assert "ix_thread_position" not in used_indexes, (
        f"Plan incorrectly used global ix_thread_position index. "
        f"Used indexes: {used_indexes}"
    )


@pytest.mark.asyncio
async def test_queue_page_index_exists(async_db_committed: AsyncSession):
    """Verify the partial index for active queue threads exists."""
    index_check = text("""
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'threads'
        AND indexname = 'ix_thread_user_active_queue_position'
    """)

    result = await async_db_committed.execute(index_check)
    index_exists = result.scalar()

    assert index_exists is not None, (
        "Index ix_thread_user_active_queue_position does not exist in database"
    )


@pytest.mark.asyncio
async def test_completed_page_uses_user_scoped_index(async_db_committed: AsyncSession):
    """Verify the completed page query can use a user-scoped index."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db_committed.add(user)
    await async_db_committed.flush()

    # Create many completed threads
    completed_threads = [
        Thread(
            user_id=user.id,
            title=f"Completed Thread {i}",
            format="Comic",
            issues_remaining=0,
            queue_position=i,
            status="completed",
            created_at=datetime.now(UTC),
        )
        for i in range(1, 101)
    ]
    async_db_committed.add_all(completed_threads)
    await async_db_committed.commit()

    await async_db_committed.execute(text("ANALYZE threads"))
    await async_db_committed.execute(text("SET LOCAL enable_seqscan = off"))
    await async_db_committed.execute(text("SET LOCAL enable_bitmapscan = off"))

    # Query pattern from fetch_completed_page for "created" sort:
    # WHERE user_id = $1 AND status = 'completed'
    # ORDER BY created_at DESC, id DESC
    # LIMIT 50
    explain_query = text("""
        EXPLAIN (ANALYZE, FORMAT JSON)
        SELECT * FROM threads
        WHERE user_id = :user_id
        AND status = 'completed'
        ORDER BY created_at DESC, id DESC
        LIMIT 50
    """)

    result = await async_db_committed.execute(explain_query, {"user_id": user.id})
    plan = result.scalar()
    assert plan is not None, "EXPLAIN query should return a plan"

    plan_data = plan if isinstance(plan, list) else [plan]

    def collect_index_names(node: dict) -> set[str]:
        index_names = set()
        index_name = node.get("Index Name")
        if isinstance(index_name, str):
            index_names.add(index_name)
        for child in node.get("Plans", []):
            index_names.update(collect_index_names(child))
        return index_names

    plan_nodes = plan_data[0]["Plan"]
    used_indexes = collect_index_names(plan_nodes)

    # Should use a user-scoped index, not a global one
    assert "ix_thread_user_status_position" in used_indexes or "ix_thread_user_active_queue_position" in used_indexes, (
        f"Plan did not reference a user-scoped index. Used indexes: {used_indexes}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])