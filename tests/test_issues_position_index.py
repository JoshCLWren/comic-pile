"""Tests for the issues position index and pagination query shape."""

import pytest
from datetime import UTC, datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User


@pytest.mark.asyncio
async def test_issues_position_index_is_used(async_db_committed: AsyncSession):
    """Verify the (thread_id, position) index exists and is usable for ordered lookups."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db_committed.add(user)
    await async_db_committed.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db_committed.add(thread)
    await async_db_committed.flush()

    # Create 50 issues with different positions
    for i in range(50):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i + 1),
            position=i + 1,
            status="unread" if i < 25 else "read",
        )
        async_db_committed.add(issue)
    await async_db_committed.commit()

    await async_db_committed.execute(text("ANALYZE issues"))
    await async_db_committed.execute(text("SET LOCAL enable_seqscan = off"))
    await async_db_committed.execute(text("SET LOCAL enable_bitmapscan = off"))

    # Get EXPLAIN plan for the query pattern used by list_issues
    explain_query = text("""
        EXPLAIN (ANALYZE, FORMAT JSON)
        SELECT * FROM issues 
        WHERE thread_id = :thread_id 
        ORDER BY position
        LIMIT 50
    """)

    result = await async_db_committed.execute(explain_query, {"thread_id": thread.id})
    plan = result.scalar()
    assert plan is not None, "EXPLAIN query should return a plan"

    # SQLAlchemy with asyncpg already deserializes JSON
    plan_data = plan if isinstance(plan, list) else [plan]

    # Extract the plan nodes
    plan_nodes = plan_data[0]["Plan"]

    # Verify we have data
    assert plan_nodes is not None

    def collect_index_names(node: dict) -> set[str]:
        """Recursively collect index names referenced in a query plan."""
        index_names = set()
        index_name = node.get("Index Name")
        if isinstance(index_name, str):
            index_names.add(index_name)
        for child in node.get("Plans", []):
            index_names.update(collect_index_names(child))
        return index_names

    assert "ix_issue_thread_position" in collect_index_names(plan_nodes), (
        "Plan did not reference ix_issue_thread_position after sequential scans were disabled."
    )

    # Also verify the index actually exists
    index_check = text("""
        SELECT 1 FROM pg_indexes 
        WHERE tablename = 'issues' 
        AND indexname = 'ix_issue_thread_position'
    """)

    index_result = await async_db_committed.execute(index_check)
    index_exists = index_result.scalar()

    assert index_exists is not None, "Index ix_issue_thread_position does not exist in database"


@pytest.mark.asyncio
async def test_issues_position_index_improves_pagination(async_db_committed: AsyncSession):
    """Verify the pagination query can use the composite position index."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db_committed.add(user)
    await async_db_committed.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db_committed.add(thread)
    await async_db_committed.flush()

    # Create 100 issues
    for i in range(100):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i + 1),
            position=i + 1,
            status="unread",
        )
        async_db_committed.add(issue)
    await async_db_committed.commit()

    await async_db_committed.execute(text("ANALYZE issues"))
    await async_db_committed.execute(text("SET LOCAL enable_seqscan = off"))
    await async_db_committed.execute(text("SET LOCAL enable_bitmapscan = off"))

    # Test pagination query pattern (like page_token usage)
    cursor_position = 50
    query = text("""
        EXPLAIN (ANALYZE, FORMAT JSON)
        SELECT * FROM issues 
        WHERE thread_id = :thread_id 
        AND (position > :cursor_position OR (position = :cursor_position AND id > :cursor_id))
        ORDER BY position, id
        LIMIT 50
    """)

    result = await async_db_committed.execute(
        query, {"thread_id": thread.id, "cursor_position": cursor_position, "cursor_id": 0}
    )
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

    assert "ix_issue_thread_position" in collect_index_names(plan_data[0]["Plan"]), (
        "Pagination plan should reference ix_issue_thread_position when sequential scans are disabled"
    )
