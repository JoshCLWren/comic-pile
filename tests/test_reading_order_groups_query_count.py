"""Regression for #3465: GET /api/v1/reading-order-groups query count.

The endpoint previously issued one membership-requery plus batched thread/issue
lookups per group (N+1). After the batch fix it must stay bounded regardless of
group/member count.
"""

import pytest
from sqlalchemy import event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.dependency_group import list_groups
from app.models import DependencyGroup, DependencyGroupMembership, Issue, Thread
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_reading_order_groups_constant_query_count(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Multiple groups with mixed members must not multiply SELECT statements."""
    user = await get_or_create_user_async(async_db)

    # Build two threads with issues, plus one bare thread.
    for idx in range(3):
        thread = Thread(
            user_id=user.id,
            title=f"Thread {idx}",
            format="Comic",
            issues_remaining=2,
            total_issues=2,
            queue_position=idx + 1,
            status="active",
        )
        async_db.add(thread)
        await async_db.flush()
        if idx < 2:
            for pos in range(1, 3):
                async_db.add(
                    Issue(
                        thread_id=thread.id,
                        issue_number=str(pos),
                        position=pos,
                        status="unread",
                    )
                )
            await async_db.flush()

    # Create two groups with mixed memberships.
    first_thread_id = thread.id
    for g_idx in range(2):
        group = DependencyGroup(
            user_id=user.id, name=f"Crossover {g_idx}"
        )
        async_db.add(group)
        await async_db.flush()
        # Thread membership on group 0, issue membership on group 1.
        if g_idx == 0:
            async_db.add(
                DependencyGroupMembership(
                    group_id=group.id, thread_id=first_thread_id
                )
            )
        else:
            result = await async_db.execute(
                select(Issue.id)
                .where(Issue.thread_id == first_thread_id)
                .order_by(Issue.id)
                .limit(1)
            )
            first_issue_id = result.scalar()
            if first_issue_id is not None:
                async_db.add(
                    DependencyGroupMembership(
                        group_id=group.id, issue_id=first_issue_id
                    )
                )
        await async_db.flush()

    await async_db.commit()

    select_statements: list[str] = []

    def _capture(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        from types import SimpleNamespace

        await list_groups(
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
        )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    # The batch design must cap SELECTs: groups + memberships (via selectinload)
    # + 2 batched metadata queries = bounded; allowing <= 5 for headroom.
    assert len(select_statements) <= 5, f"Too many SELECTs ({len(select_statements)}): {select_statements}"
