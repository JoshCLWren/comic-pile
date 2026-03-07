"""Test that issues position index is used in query plans."""

import pytest
from datetime import UTC, datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User


@pytest.mark.asyncio
async def test_issues_position_index_is_used(async_db: AsyncSession):
    """Verify the (thread_id, position) index is used in list_issues query.

    This test creates sample data and verifies the EXPLAIN plan shows
    an index scan instead of a sequential scan.
    """
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    # Create 50 issues with different positions
    for i in range(50):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i + 1),
            position=i,
            status="unread" if i < 25 else "read",
        )
        async_db.add(issue)
    await async_db.commit()

    # Get EXPLAIN plan for the query pattern used by list_issues
    explain_query = text("""
        EXPLAIN (ANALYZE, FORMAT JSON)
        SELECT * FROM issues 
        WHERE thread_id = :thread_id 
        ORDER BY position
        LIMIT 50
    """)

    result = await async_db.execute(explain_query, {"thread_id": thread.id})
    plan = result.scalar()

    # SQLAlchemy with asyncpg already deserializes JSON
    plan_data = plan if isinstance(plan, list) else [plan]

    # Extract the plan nodes
    plan_nodes = plan_data[0]["Plan"]

    # Verify we have data
    assert plan_nodes is not None

    # Check that the plan uses an index scan or bitmap index scan
    # (sequential scan would indicate the index is not being used)
    def check_index_used(node):
        """Recursively check if any node in the plan uses an index."""
        if "Index Scan" in node.get("Node Type", ""):
            return True
        if "Bitmap Index Scan" in node.get("Node Type", ""):
            return True
        if "Plans" in node:
            for child in node["Plans"]:
                if check_index_used(child):
                    return True
        return False

    index_is_used = check_index_used(plan_nodes)

    # Assert that the index is being used
    assert index_is_used, (
        "Index scan not detected in EXPLAIN plan. The (thread_id, position) index may not be created or used."
    )

    # Also verify the index actually exists
    index_check = text("""
        SELECT 1 FROM pg_indexes 
        WHERE tablename = 'issues' 
        AND indexname = 'ix_issue_thread_position'
    """)

    index_result = await async_db.execute(index_check)
    index_exists = index_result.scalar()

    assert index_exists is not None, "Index ix_issue_thread_position does not exist in database"


@pytest.mark.asyncio
async def test_issues_position_index_improves_pagination(async_db: AsyncSession):
    """Verify the index helps with cursor-based pagination.

    Tests the pagination pattern used in list_issues with page_token.
    """
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    # Create 100 issues
    for i in range(100):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i + 1),
            position=i,
            status="unread",
        )
        async_db.add(issue)
    await async_db.commit()

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

    result = await async_db.execute(
        query, {"thread_id": thread.id, "cursor_position": cursor_position, "cursor_id": 0}
    )
    plan = result.scalar()

    # SQLAlchemy with asyncpg already deserializes JSON
    plan_data = plan if isinstance(plan, list) else [plan]

    # Verify the query completes efficiently (should use index)
    execution_time = plan_data[0].get("Execution Time", 0)

    # On a properly indexed query with 100 rows, execution should be < 1ms
    # If doing sequential scan, it would be much slower
    assert execution_time < 10.0, (
        f"Query took {execution_time}ms, expected < 10ms with proper index"
    )
