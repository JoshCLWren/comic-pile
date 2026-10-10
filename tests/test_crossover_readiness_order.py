"""Canonical readiness regressions for legacy crossover display ordering.

Display order never blocks. Explicit hard Dependencies compose across groups,
use global read state, and remain authoritative when display order changes.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_blocking import get_continuity_blocked_thread_ids
from app.models.dependency import Dependency
from sqlalchemy import select
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.issue import Issue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async
from comic_pile.dependencies import refresh_user_blocked_status


async def _make_thread_with_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    issue_number: str = "1",
) -> tuple[Thread, Issue]:
    """Create one owned thread with a single unread issue."""
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id
    await db.flush()
    return thread, issue


async def _make_ordered_crossover(
    db: AsyncSession,
    *,
    user_id: int,
    name: str,
    entries: list[tuple[Issue, int]],
) -> DependencyGroup:
    """Create one crossover whose issue members carry an display order."""
    group = DependencyGroup(user_id=user_id, name=name)
    db.add(group)
    await db.flush()
    for issue, sequence_order in entries:
        db.add(
            DependencyGroupMembership(
                group_id=group.id,
                issue_id=issue.id,
                sequence_order=sequence_order,
            )
        )
    await db.flush()
    return group


@pytest.mark.asyncio
async def test_later_display_entry_remains_eligible_without_hard_dependency(
    async_db: AsyncSession,
) -> None:
    """An unread earlier display entry cannot create a hard prerequisite."""
    user = await get_or_create_user_async(async_db)
    first_thread, first_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Ultimates source", queue_position=701
    )
    second_thread, second_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Later crossover entry", queue_position=702
    )
    await _make_ordered_crossover(
        async_db,
        user_id=user.id,
        name="The Ultimates Order",
        entries=[(first_issue, 1), (second_issue, 2)],
    )
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert second_thread.id not in blocked
    assert first_thread.id not in blocked


@pytest.mark.asyncio
async def test_reading_earlier_entry_unblocks_later_entry_globally(
    async_db: AsyncSession,
) -> None:
    """Read state is global: reading the earlier entry unblocks the later one."""
    user = await get_or_create_user_async(async_db)
    first_thread, first_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Sequence first", queue_position=703
    )
    second_thread, second_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Sequence second", queue_position=704
    )
    await _make_ordered_crossover(
        async_db,
        user_id=user.id,
        name="Sequence",
        entries=[(first_issue, 1), (second_issue, 2)],
    )
    await async_db.commit()

    first_issue.status = "read"
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert second_thread.id not in blocked
    assert first_thread.id not in blocked


@pytest.mark.asyncio
async def test_sparse_display_order_does_not_block_later_unread_entries(
    async_db: AsyncSession,
) -> None:
    """Sparse display positions do not become canonical hard constraints."""
    user = await get_or_create_user_async(async_db)
    threads: list[Thread] = []
    issues: list[Issue] = []
    for index in range(4):
        thread, issue = await _make_thread_with_issue(
            async_db,
            user_id=user.id,
            title=f"Entry {index + 1}",
            queue_position=710 + index,
        )
        threads.append(thread)
        issues.append(issue)
    await _make_ordered_crossover(
        async_db,
        user_id=user.id,
        name="Quad",
        entries=[(issue, index + 1) for index, issue in enumerate(issues)],
    )
    await async_db.commit()

    issues[0].status = "read"
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert blocked == set()
    assert list((await async_db.scalars(select(Dependency))).all()) == []


@pytest.mark.asyncio
async def test_explicit_dependencies_compose_across_display_crossovers(
    async_db: AsyncSession,
) -> None:
    """Two explicit hard prerequisites compose independently of display groups."""
    user = await get_or_create_user_async(async_db)
    a_thread, a_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Crossover A first", queue_position=720
    )
    b_thread, b_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Crossover B first", queue_position=721
    )
    target_thread, target_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Shared later entry", queue_position=722
    )
    await _make_ordered_crossover(
        async_db,
        user_id=user.id,
        name="Crossover A",
        entries=[(a_issue, 1), (target_issue, 2)],
    )
    await _make_ordered_crossover(
        async_db,
        user_id=user.id,
        name="Crossover B",
        entries=[(b_issue, 1), (target_issue, 2)],
    )
    await async_db.commit()

    assert await get_continuity_blocked_thread_ids(user.id, async_db) == set()
    async_db.add_all(
        [
            Dependency(source_issue_id=a_issue.id, target_issue_id=target_issue.id),
            Dependency(source_issue_id=b_issue.id, target_issue_id=target_issue.id),
        ]
    )
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert target_thread.id in blocked

    b_issue.status = "read"
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert target_thread.id in blocked

    a_issue.status = "read"
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert target_thread.id not in blocked


@pytest.mark.asyncio
async def test_explicit_prerequisite_is_independent_of_crossover_display_order(
    async_db: AsyncSession,
) -> None:
    """A hard prerequisite blocks; an unread earlier display entry does not."""
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Series prerequisite", queue_position=730
    )
    ordered_first_thread, ordered_first_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Crossover first", queue_position=731
    )
    target_thread, target_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Composed target", queue_position=732
    )
    async_db.add(Dependency(source_issue_id=source_issue.id, target_issue_id=target_issue.id))
    await _make_ordered_crossover(
        async_db,
        user_id=user.id,
        name="Series order",
        entries=[(ordered_first_issue, 1), (target_issue, 2)],
    )
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert target_thread.id in blocked

    source_issue.status = "read"
    assert ordered_first_issue.status == "unread"
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert target_thread.id not in blocked
    assert source_thread.id not in blocked
    assert ordered_first_thread.id not in blocked


@pytest.mark.asyncio
async def test_the_ultimates_18_requires_explicit_hard_intent_to_block(
    async_db: AsyncSession,
) -> None:
    """Ultimates #16 gates #18 only through an explicit canonical Dependency."""
    user = await get_or_create_user_async(async_db)
    ultimates_thread, ultimates_16 = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="The Ultimates",
        queue_position=740,
        issue_number="16",
    )
    ultimates_18_thread, ultimates_18 = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="The Ultimates",
        queue_position=741,
        issue_number="18",
    )
    await _make_ordered_crossover(
        async_db,
        user_id=user.id,
        name="The Ultimates Run",
        entries=[(ultimates_16, 1), (ultimates_18, 2)],
    )
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert ultimates_18_thread.id not in blocked
    async_db.add(Dependency(source_issue_id=ultimates_16.id, target_issue_id=ultimates_18.id))
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert ultimates_18_thread.id in blocked
    assert ultimates_thread.id not in blocked

    ultimates_16.status = "read"
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert ultimates_18_thread.id not in blocked


@pytest.mark.asyncio
async def test_reorder_endpoint_persists_display_order_without_changing_hard_constraints(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """PUT /{group_id}/order persists display order and gates readiness.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    first_thread, first_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Reorder first", queue_position=750
    )
    second_thread, second_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Reorder second", queue_position=751
    )
    group = DependencyGroup(user_id=user.id, name="Reorder crossover")
    async_db.add(group)
    await async_db.flush()
    async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=first_issue.id))
    async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=second_issue.id))
    await async_db.commit()

    response = await auth_client.put(
        f"/api/v1/reading-order-groups/{group.id}/order",
        json={
            "items": [
                {"issue_id": first_issue.id, "sequence_order": 1},
                {"issue_id": second_issue.id, "sequence_order": 2},
            ]
        },
    )
    assert response.status_code == 200, response.text
    members_by_issue = {member["issue_id"]: member for member in response.json()["memberships"]}
    assert members_by_issue[first_issue.id]["sequence_order"] == 1
    assert members_by_issue[second_issue.id]["sequence_order"] == 2

    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert second_thread.id not in blocked
    assert first_thread.id not in blocked
    assert list((await async_db.scalars(select(Dependency))).all()) == []
    async_db.add(Dependency(source_issue_id=first_issue.id, target_issue_id=second_issue.id))
    await async_db.commit()
    response = await auth_client.put(
        f"/api/v1/reading-order-groups/{group.id}/order",
        json={
            "items": [
                {"issue_id": first_issue.id, "sequence_order": 2},
                {"issue_id": second_issue.id, "sequence_order": 1},
            ]
        },
    )
    assert response.status_code == 200, response.text
    blocked = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert blocked == {second_thread.id}
    deps = list((await async_db.scalars(select(Dependency))).all())
    assert [(dep.source_issue_id, dep.target_issue_id) for dep in deps] == [
        (first_issue.id, second_issue.id)
    ]


@pytest.mark.asyncio
async def test_add_member_persists_sequence_order(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """POST member with sequence_order stores it and returns it in the response."""
    user = await get_or_create_user_async(async_db)
    _thread, issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Ordered member", queue_position=752
    )
    group = DependencyGroup(user_id=user.id, name="Single ordered crossover")
    async_db.add(group)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/reading-order-groups/{group.id}/members",
        json={"issue_id": issue.id, "sequence_order": 5},
    )
    assert response.status_code == 201, response.text
    assert response.json()["sequence_order"] == 5


@pytest.mark.asyncio
async def test_reorder_endpoint_rejects_member_duplicates(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """PUT /{group_id}/order rejects an issue listed twice."""
    user = await get_or_create_user_async(async_db)
    _thread, issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Duplicate order", queue_position=753
    )
    group = DependencyGroup(user_id=user.id, name="Duplicate crossover")
    async_db.add(group)
    await async_db.flush()
    async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue.id))
    await async_db.commit()

    response = await auth_client.put(
        f"/api/v1/reading-order-groups/{group.id}/order",
        json={
            "items": [
                {"issue_id": issue.id, "sequence_order": 1},
                {"issue_id": issue.id, "sequence_order": 2},
            ]
        },
    )
    assert response.status_code == 422, response.text
