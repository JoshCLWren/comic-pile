"""Tests for the dependencies target_issue_id index used by blocked-thread joins."""

import pytest
from datetime import UTC, datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread, User


@pytest.mark.asyncio
async def test_dependencies_target_issue_id_index_exists(async_db_committed: AsyncSession):
    """Verify the target_issue_id index exists in the database."""
    index_check = text("""
        SELECT 1 FROM pg_indexes 
        WHERE tablename = 'dependencies' 
        AND indexname = 'ix_dependencies_target_issue_id'
    """)

    result = await async_db_committed.execute(index_check)
    index_exists = result.scalar()

    assert index_exists is not None, "Index ix_dependencies_target_issue_id does not exist in database"


@pytest.mark.asyncio
async def test_dependencies_target_issue_id_index_is_used(async_db_committed: AsyncSession):
    """Verify the target_issue_id index is used for reverse dependency lookups."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db_committed.add(user)
    await async_db_committed.flush()

    # Create source thread with issue
    source_thread = Thread(
        title="Source Thread",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db_committed.add(source_thread)
    await async_db_committed.flush()

    source_issue = Issue(
        thread_id=source_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db_committed.add(source_issue)
    await async_db_committed.flush()

    # Create target thread with issue
    target_thread = Thread(
        title="Target Thread",
        format="comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db_committed.add(target_thread)
    await async_db_committed.flush()

    target_issue = Issue(
        thread_id=target_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db_committed.add(target_issue)
    await async_db_committed.flush()

    # Link them with a dependency
    dep = Dependency(
        source_issue_id=source_issue.id,
        target_issue_id=target_issue.id,
    )
    async_db_committed.add(dep)
    await async_db_committed.commit()

    # Create more dependencies to make index worthwhile
    for i in range(2, 100):
        t = Thread(
            title=f"Target Thread {i}",
            format="comic",
            issues_remaining=1,
            queue_position=i + 1,
            status="active",
            user_id=user.id,
        )
        async_db_committed.add(t)
        await async_db_committed.flush()

        iss = Issue(
            thread_id=t.id,
            issue_number="1",
            position=1,
            status="unread",
        )
        async_db_committed.add(iss)
        await async_db_committed.flush()

        d = Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=iss.id,
        )
        async_db_committed.add(d)

    await async_db_committed.commit()

    # Analyze and disable sequential scans
    await async_db_committed.execute(text("ANALYZE dependencies"))
    await async_db_committed.execute(text("SET LOCAL enable_seqscan = off"))
    await async_db_committed.execute(text("SET LOCAL enable_bitmapscan = off"))

    # This query pattern matches _get_legacy_blocked_thread_ids_uncached:
    # Join Dependency on target_issue_id to find blocked threads
    explain_query = text("""
        EXPLAIN (ANALYZE, FORMAT JSON)
        SELECT DISTINCT t.id
        FROM threads t
        JOIN issues i ON i.thread_id = t.id
        JOIN dependencies d ON d.target_issue_id = i.id
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        WHERE t.user_id = :user_id
        AND st.user_id = :user_id
        AND si.status != 'read'
        AND t.next_unread_issue_id IS NOT NULL
    """)

    result = await async_db_committed.execute(explain_query, {"user_id": user.id})
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

    assert "ix_dependencies_target_issue_id" in collect_index_names(plan_nodes), (
        "Plan did not reference ix_dependencies_target_issue_id after sequential scans were disabled. "
        f"Found indexes: {collect_index_names(plan_nodes)}"
    )


@pytest.mark.asyncio
async def test_legacy_blocking_explanations_uses_index(async_db_committed: AsyncSession):
    """Verify the _legacy_blocking_explanations query uses the target_issue_id index."""
    user = User(username="test_user2", created_at=datetime.now(UTC))
    async_db_committed.add(user)
    await async_db_committed.flush()

    source_thread = Thread(
        title="Source Thread",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db_committed.add(source_thread)
    await async_db_committed.flush()

    source_issue = Issue(
        thread_id=source_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db_committed.add(source_issue)
    await async_db_committed.flush()

    target_thread = Thread(
        title="Target Thread",
        format="comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db_committed.add(target_thread)
    await async_db_committed.flush()

    target_issue = Issue(
        thread_id=target_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db_committed.add(target_issue)
    await async_db_committed.flush()

    target_thread.next_unread_issue_id = target_issue.id
    await async_db_committed.flush()

    dep = Dependency(
        source_issue_id=source_issue.id,
        target_issue_id=target_issue.id,
    )
    async_db_committed.add(dep)
    await async_db_committed.commit()

    # Create more data to make index worthwhile
    for i in range(2, 100):
        t = Thread(
            title=f"Target Thread {i}",
            format="comic",
            issues_remaining=1,
            queue_position=i + 1,
            status="active",
            user_id=user.id,
        )
        async_db_committed.add(t)
        await async_db_committed.flush()

        iss = Issue(
            thread_id=t.id,
            issue_number="1",
            position=1,
            status="unread",
        )
        async_db_committed.add(iss)
        await async_db_committed.flush()

        d = Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=iss.id,
        )
        async_db_committed.add(d)

    await async_db_committed.commit()

    await async_db_committed.execute(text("ANALYZE dependencies"))
    await async_db_committed.execute(text("SET LOCAL enable_seqscan = off"))
    await async_db_committed.execute(text("SET LOCAL enable_bitmapscan = off"))

    # This query pattern matches _legacy_blocking_explanations:
    explain_query = text("""
        EXPLAIN (ANALYZE, FORMAT JSON)
        SELECT
            st.id,
            st.title,
            si.id,
            si.issue_number
        FROM threads tt
        JOIN issues i ON i.id = tt.next_unread_issue_id
        JOIN dependencies d ON d.target_issue_id = i.id
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        WHERE tt.id = :thread_id
        AND tt.user_id = :user_id
        AND st.user_id = :user_id
        AND si.status != 'read'
        AND tt.next_unread_issue_id IS NOT NULL
    """)

    result = await async_db_committed.execute(explain_query, {"thread_id": target_thread.id, "user_id": user.id})
    plan = result.scalar()
    assert plan is not None, "EXPLAIN query should return a plan"

    plan_data = plan if isinstance(plan, list) else [plan]
    plan_nodes = plan_data[0]["Plan"]

    def collect_index_names(node: dict) -> set[str]:
        index_names = set()
        index_name = node.get("Index Name")
        if isinstance(index_name, str):
            index_names.add(index_name)
        for child in node.get("Plans", []):
            index_names.update(collect_index_names(child))
        return index_names

    assert "ix_dependencies_target_issue_id" in collect_index_names(plan_nodes), (
        "Plan did not reference ix_dependencies_target_issue_id after sequential scans were disabled. "
        f"Found indexes: {collect_index_names(plan_nodes)}"
    )


@pytest.mark.asyncio
async def test_batch_blocking_explanations_uses_index(async_db_committed: AsyncSession):
    """Verify the _legacy_blocking_explanations_batch query uses the target_issue_id index."""
    user = User(username="test_user3", created_at=datetime.now(UTC))
    async_db_committed.add(user)
    await async_db_committed.flush()

    thread_ids = []
    for i in range(50):
        t = Thread(
            title=f"Target Thread {i}",
            format="comic",
            issues_remaining=1,
            queue_position=i + 1,
            status="active",
            user_id=user.id,
        )
        async_db_committed.add(t)
        await async_db_committed.flush()

        iss = Issue(
            thread_id=t.id,
            issue_number="1",
            position=1,
            status="unread",
        )
        async_db_committed.add(iss)
        await async_db_committed.flush()

        t.next_unread_issue_id = iss.id
        await async_db_committed.flush()
        thread_ids.append(t.id)

    # Create a source thread and issue
    source_thread = Thread(
        title="Source Thread",
        format="comic",
        issues_remaining=1,
        queue_position=100,
        status="active",
        user_id=user.id,
    )
    async_db_committed.add(source_thread)
    await async_db_committed.flush()

    source_issue = Issue(
        thread_id=source_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db_committed.add(source_issue)
    await async_db_committed.flush()

    # Create dependencies from source to all targets
    for target_id in thread_ids:
        target_issue_result = await async_db_committed.execute(
            text("SELECT next_unread_issue_id FROM threads WHERE id = :tid"), {"tid": target_id}
        )
        target_issue_id = target_issue_result.scalar()
        
        dep = Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=target_issue_id,
        )
        async_db_committed.add(dep)

    await async_db_committed.commit()

    await async_db_committed.execute(text("ANALYZE dependencies"))
    await async_db_committed.execute(text("SET LOCAL enable_seqscan = off"))
    await async_db_committed.execute(text("SET LOCAL enable_bitmapscan = off"))

    # This query pattern matches _legacy_blocking_explanations_batch:
    thread_ids_str = ",".join(str(tid) for tid in thread_ids)
    explain_query = text(f"""
        EXPLAIN (ANALYZE, FORMAT JSON)
        SELECT
            tt.id,
            st.id,
            st.title,
            si.id,
            si.issue_number
        FROM threads tt
        JOIN issues i ON i.id = tt.next_unread_issue_id
        JOIN dependencies d ON d.target_issue_id = i.id
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        WHERE tt.id IN ({thread_ids_str})
        AND tt.user_id = :user_id
        AND st.user_id = :user_id
        AND si.status != 'read'
        AND tt.next_unread_issue_id IS NOT NULL
    """)

    result = await async_db_committed.execute(explain_query, {"user_id": user.id})
    plan = result.scalar()
    assert plan is not None, "EXPLAIN query should return a plan"

    plan_data = plan if isinstance(plan, list) else [plan]
    plan_nodes = plan_data[0]["Plan"]

    def collect_index_names(node: dict) -> set[str]:
        index_names = set()
        index_name = node.get("Index Name")
        if isinstance(index_name, str):
            index_names.add(index_name)
        for child in node.get("Plans", []):
            index_names.update(collect_index_names(child))
        return index_names

    assert "ix_dependencies_target_issue_id" in collect_index_names(plan_nodes), (
        "Plan did not reference ix_dependencies_target_issue_id after sequential scans were disabled. "
        f"Found indexes: {collect_index_names(plan_nodes)}"
    )
