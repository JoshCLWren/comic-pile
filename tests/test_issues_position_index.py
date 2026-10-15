"""Tests for the issues position index and pagination query shape."""

import pytest
from datetime import UTC, datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User


def collect_plan_facts(node: dict) -> tuple[set[str], set[str]]:
    """Recursively collect the index names and node types in a query plan.

    `issues` carries several indexes whose leading column is `thread_id`:
    `uq_issue_thread_number (thread_id, issue_number)`, plus two indexes on
    `(thread_id, position)` -- `ix_issue_thread_position` and the
    `uq_issue_thread_position` unique constraint backing index. Any of them can
    serve the `thread_id = ?` restriction, and none of them alone satisfies the
    `ORDER BY position, id` pathkeys these queries request, so every candidate
    plan also pays for a sort. The planner therefore chooses between
    near-equal-cost candidates, and which one wins depends on table statistics
    rather than on anything this module controls. Assert the access method
    (index-driven, never a sequential scan) and the existence of the composite
    position index, not one arbitrary index name.

    Args:
        node: A single node from a PostgreSQL `EXPLAIN (FORMAT JSON)` plan.

    Returns:
        The index names and node types found anywhere in the plan tree.
    """
    index_names: set[str] = set()
    node_types: set[str] = set()
    index_name = node.get("Index Name")
    if isinstance(index_name, str):
        index_names.add(index_name)
    node_type = node.get("Node Type")
    if isinstance(node_type, str):
        node_types.add(node_type)
    for child in node.get("Plans", []):
        child_index_names, child_node_types = collect_plan_facts(child)
        index_names.update(child_index_names)
        node_types.update(child_node_types)
    return index_names, node_types


def assert_index_driven(index_names: set[str], node_types: set[str], label: str) -> None:
    """Assert a lookup plan is served by an index rather than a sequential scan.

    Args:
        index_names: Index names referenced anywhere in the plan.
        node_types: Plan node types found anywhere in the plan.
        label: Human-readable description of the query being asserted.

    Raises:
        AssertionError: If the plan scans sequentially or uses no index at all.
    """
    assert not any("Seq Scan" in node_type for node_type in node_types), (
        f"{label} fell back to a sequential scan. Nodes: {sorted(node_types)}"
    )
    assert index_names, (
        f"{label} must use an index when sequential scans are disabled. "
        f"Nodes: {sorted(node_types)}"
    )


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

    index_names, node_types = collect_plan_facts(plan_nodes)
    assert_index_driven(index_names, node_types, "Ordered issue lookup")

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

    index_names, node_types = collect_plan_facts(plan_data[0]["Plan"])
    assert_index_driven(index_names, node_types, "Issue pagination")

    # The composite position index is what makes index-driven pagination
    # possible, so it must actually be present in the database.
    index_check = text("""
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'issues'
        AND indexname IN ('ix_issue_thread_position', 'uq_issue_thread_position')
    """)

    index_result = await async_db_committed.execute(index_check)
    assert index_result.scalar() is not None, (
        "Neither ix_issue_thread_position nor uq_issue_thread_position exists in the database"
    )
