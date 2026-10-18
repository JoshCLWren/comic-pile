"""Progress accounting for GET /v1/reading-order-groups (#3522).

Each event row must report best-effort reading progress derived from member
data without breaking the flat query budget documented in
``test_reading_order_groups_query_count.py``: migrated series contribute
issue-derived totals, direct issue members count individually, an issue inside
an already-membered series never double counts, and legacy series without a
migrated total contribute nothing.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency_group import list_groups
from app.models import DependencyGroup, DependencyGroupMembership, Issue, Thread
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_list_groups_reports_member_progress(async_db: AsyncSession) -> None:
    """Rows blend series totals, direct issue members, and de-duplicated ranges."""
    user = await get_or_create_user_async(async_db)

    # Migrated whole-series member: four issues, one still unread, so three read.
    migrated = Thread(
        user_id=user.id,
        title="Saga",
        format="Comic",
        total_issues=4,
        issues_remaining=1,
        queue_position=1,
        status="active",
    )
    async_db.add(migrated)
    await async_db.flush()
    saga_read_issues = [
        Issue(thread_id=migrated.id, issue_number=str(n), position=n, status="read") for n in (1, 2, 3)
    ]
    async_db.add_all(
        saga_read_issues + [Issue(thread_id=migrated.id, issue_number="4", position=4, status="unread")]
    )
    await async_db.flush()
    saga_issues = (
        (await async_db.execute(select(Issue).where(Issue.thread_id == migrated.id))).scalars().all()
    )

    other = Thread(
        user_id=user.id,
        title="Doomed Patrol",
        format="Comic",
        total_issues=2,
        issues_remaining=2,
        queue_position=2,
        status="active",
    )
    async_db.add(other)
    await async_db.flush()
    other_issue = Issue(thread_id=other.id, issue_number="1", position=1, status="unread")
    async_db.add(other_issue)
    await async_db.flush()

    legacy = Thread(
        user_id=user.id,
        title="Classic Sprint",
        format="Comic",
        issues_remaining=5,
        queue_position=3,
        status="active",
    )
    async_db.add(legacy)
    await async_db.flush()

    group = DependencyGroup(user_id=user.id, name="Mixed crossover")
    async_db.add(group)
    await async_db.flush()
    async_db.add_all(
        [
            DependencyGroupMembership(group_id=group.id, thread_id=migrated.id),
            DependencyGroupMembership(group_id=group.id, issue_id=other_issue.id),
            DependencyGroupMembership(group_id=group.id, thread_id=legacy.id),
            # A range inside an already-membered series: counted once, twice never.
            DependencyGroupMembership(group_id=group.id, issue_id=saga_issues[0].id),
        ]
    )
    empty_group = DependencyGroup(user_id=user.id, name="Empty crossover")
    async_db.add(empty_group)
    await async_db.flush()
    await async_db.commit()

    responses = await list_groups(current_user=SimpleNamespace(id=user.id), db=async_db)
    by_name = {response.name: response for response in responses}

    mixed = by_name["Mixed crossover"]
    assert (mixed.read_issues, mixed.total_issues) == (3, 5)
    assert mixed.reading_progress == "60%"

    empty = by_name["Empty crossover"]
    assert (empty.read_issues, empty.total_issues, empty.reading_progress) == (0, 0, "0%")
