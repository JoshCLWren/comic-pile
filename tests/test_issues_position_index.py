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
    await async_db_committed.execute(text("SET LOCAL enable_indexonlyscan = off"))

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

    # With sequential scans and bitmap scans disabled the planner must reach an
    # index to answer a thread-scoped lookup. The position index (thread_id, position)
    # is the index that serves both the WHERE and ORDER BY for this query pattern.
    # Verify it appears in the plan; if the planner chooses a different thread-scoped
    # index, the test will fail and alert us to investigate rather than silently
    # accepting a plan that cannot guarantee ordered results without a sort.
    index_names = collect_index_names(plan_nodes)
    assert index_names, (
        "Plan used no index after sequential and bitmap scans were disabled; "
        f"the thread-scoped lookup is not indexed: {plan_nodes}"
    )
    assert any(
        name in index_names
        for name in ("ix_issue_thread_position", "uq_issue_thread_position")
    ), (
        f"No position index used in plan; indexes found: {index_names}; "
        f"plan: {plan_nodes}"
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

    # The real query must return the issues in position order regardless of which
    # index the planner chose, so exercise the actual lookup instead of trusting
    # the plan shape alone.
    rows = await async_db_committed.execute(
        text("""
            SELECT position FROM issues
            WHERE thread_id = :thread_id
            ORDER BY position
            LIMIT 50
        """),
        {"thread_id": thread.id},
    )
    positions = [row[0] for row in rows.all()]
    assert positions == list(range(1, 51)), (
        f"Indexed lookup did not return issues in position order: {positions[:5]}..."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("incremental_sort", ["on", "off"])
async def test_issues_position_index_improves_pagination(
    async_db_committed: AsyncSession, incremental_sort: str,
) -> None:
    """Verify indexed keyset pagination preserves the cursor boundary and issue order."""
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

    # Reverse ID/position correlation so reading ID order cannot accidentally
    # satisfy the pagination contract. The cursor is an actual existing Issue.
    cursor_id = 0
    for i in range(100):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i + 1),
            position=100 - i,
            status="unread",
        )
        async_db_committed.add(issue)
        if issue.position == 50:
            await async_db_committed.flush()
            cursor_id = issue.id
    await async_db_committed.commit()

    await async_db_committed.execute(text("ANALYZE issues"))
    await async_db_committed.execute(text("SET LOCAL enable_seqscan = off"))
    await async_db_committed.execute(text("SET LOCAL enable_bitmapscan = off"))
    await async_db_committed.execute(text("SET LOCAL enable_indexonlyscan = off"))

    await async_db_committed.execute(
        text(f"SET LOCAL enable_incremental_sort = {incremental_sort}")
    )

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
        query, {"thread_id": thread.id, "cursor_position": cursor_position, "cursor_id": cursor_id}
    )
    plan = result.scalar()
    assert plan is not None, "EXPLAIN query should return a plan"

    # SQLAlchemy with asyncpg already deserializes JSON
    plan_data = plan if isinstance(plan, list) else [plan]

    def collect_thread_lookup_indexes(node: dict[str, object]) -> set[str]:
        """Find indexed lookups bounded by the requested Thread."""
        names: set[str] = set()
        name = node.get("Index Name")
        condition = node.get("Index Cond")
        if isinstance(name, str) and isinstance(condition, str) and "thread_id" in condition:
            names.add(name)
        children = node.get("Plans")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    names.update(collect_thread_lookup_indexes(child))
        return names

    # PostgreSQL may prefer the ownership FK's (thread_id, id) index and sort
    # this small page, rather than use (thread_id, position). Require the
    # intended bounded index lookup, not one optimizer-dependent index name.
    index_names = collect_thread_lookup_indexes(plan_data[0]["Plan"])
    assert index_names, "Pagination must use an index condition on thread_id"
    page = await async_db_committed.execute(
        text("""
            SELECT id, thread_id, position FROM issues
            WHERE thread_id = :thread_id
            AND (position > :cursor_position OR
                 (position = :cursor_position AND id > :cursor_id))
            ORDER BY position, id
            LIMIT 50
        """),
        {"thread_id": thread.id, "cursor_position": cursor_position, "cursor_id": cursor_id},
    )
    rows = page.all()
    assert [row.position for row in rows] == list(range(51, 101))
    assert all(row.thread_id == thread.id for row in rows)


@pytest.mark.asyncio
async def test_issue_model_indexes_survive_committed_fixture(async_db_committed: AsyncSession):
    """Verify the committed fixture leaves the model-declared issue indexes intact."""
    result = await async_db_committed.execute(
        text(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'issues' "
            "AND indexname IN ('ix_issue_thread_id', 'ix_issue_thread_is_read')"
        )
    )
    names = {row[0] for row in result.all()}
    assert names == {"ix_issue_thread_id", "ix_issue_thread_is_read"}
