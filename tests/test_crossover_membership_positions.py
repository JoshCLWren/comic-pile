"""Regression coverage for authoritative crossover membership positions.

Issue #2040: crossover order must come from the group's stored authoritative
sequence, never from each issue's series-local ``position``. These tests use a
realistic multi-series fixture where several series reuse local positions ``1``,
``2``, ``3`` so a per-series sort would fabricate a sequence that never existed.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.dependency_group import DependencyGroup


def _unique_name(prefix: str) -> str:
    """Build a collision-free group name for repeatable test runs."""
    return f"{prefix} {uuid.uuid4().hex[:8]}"


async def _make_thread(
    db: AsyncSession,
    user: User,
    *,
    title: str,
    issue_count: int,
    queue_position: int,
) -> tuple[Thread, list[Issue]]:
    """Create an owned thread with contiguous locally-positioned issues."""
    thread = Thread(
        user_id=user.id,
        title=title,
        format="Comic",
        issues_remaining=issue_count,
        total_issues=issue_count,
        queue_position=queue_position,
        status="active",
    )
    db.add(thread)
    await db.flush()
    issues = []
    for position in range(1, issue_count + 1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status="unread",
        )
        db.add(issue)
        issues.append(issue)
    await db.flush()
    return thread, issues


async def _make_group(db: AsyncSession, user: User, name: str) -> DependencyGroup:
    """Create and commit an owned empty group."""
    group = DependencyGroup(user_id=user.id, name=name)
    db.add(group)
    await db.commit()
    return group


@pytest.mark.asyncio
async def test_add_members_assign_sequential_authoritative_positions(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Single-member adds append to the authoritative sequence."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Nova", issue_count=3, queue_position=90
    )
    group = await _make_group(async_db, default_user, _unique_name("Sequential"))

    for issue in issues:
        response = await auth_client.post(
            f"/api/v1/reading-order-groups/{group.id}/members",
            json={"issue_id": issue.id},
        )
        assert response.status_code == 201

    follow_up = await auth_client.get(f"/api/v1/reading-order-groups/{group.id}")
    assert follow_up.status_code == 200
    members = follow_up.json()["memberships"]
    assert [member["sequence_order"] for member in members] == [1, 2, 3]
    assert [member["issue_id"] for member in members] == [issues[0].id, issues[1].id, issues[2].id]


@pytest.mark.asyncio
async def test_order_is_never_derived_from_series_local_positions(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Cross-series order follows membership slots, not local issue positions.

    Two series both use local positions ``1..3``. A member added first at local
    position 3 must stay before a later member at local position 1; sorting the
    payloads by ``issue.position`` would silently invert them.
    """
    alpha, alpha_issues = await _make_thread(
        async_db, default_user, title="Alpha", issue_count=3, queue_position=91
    )
    beta, beta_issues = await _make_thread(
        async_db, default_user, title="Beta", issue_count=3, queue_position=92
    )
    group = await _make_group(async_db, default_user, _unique_name("CrossSeries"))

    order = await auth_client.post(
        f"/api/v1/reading-order-groups/{group.id}/members",
        json={"issue_id": alpha_issues[2].id},
    )
    assert order.status_code == 201
    assert order.json()["sequence_order"] == 1

    second = await auth_client.post(
        f"/api/v1/reading-order-groups/{group.id}/members",
        json={"issue_id": beta_issues[0].id},
    )
    assert second.status_code == 201
    assert second.json()["sequence_order"] == 2

    follow_up = await auth_client.get(f"/api/v1/reading-order-groups/{group.id}")
    assert follow_up.status_code == 200
    members = follow_up.json()["memberships"]
    assert [member["sequence_order"] for member in members] == [1, 2]
    assert [member["issue_id"] for member in members] == [
        alpha_issues[2].id,  # series-local position 3
        beta_issues[0].id,  # series-local position 1, but authored later
    ]


@pytest.mark.asyncio
async def test_issue_range_assigns_positions_in_authoritative_source_order(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Issue-range adds hold source order and skip already-present members."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Warlock", issue_count=3, queue_position=93
    )
    group = await _make_group(async_db, default_user, _unique_name("Range"))

    preexisting = await auth_client.post(
        f"/api/v1/reading-order-groups/{group.id}/members",
        json={"issue_id": issues[2].id},
    )
    assert preexisting.status_code == 201

    ranged = await auth_client.post(
        f"/api/v1/reading-order-groups/{group.id}/issue-ranges",
        json={"thread_id": thread.id, "start_position": 1, "end_position": 3},
    )
    assert ranged.status_code == 200
    payload = ranged.json()
    assert sorted(payload["added_issue_ids"]) == sorted([issues[0].id, issues[1].id])
    assert payload["already_present_issue_ids"] == [issues[2].id]

    follow_up = await auth_client.get(f"/api/v1/reading-order-groups/{group.id}")
    assert follow_up.status_code == 200
    members = follow_up.json()["memberships"]
    assert [member["sequence_order"] for member in members] == [1, 2, 3]
    assert [member["issue_id"] for member in members] == [
        issues[2].id,
        issues[0].id,
        issues[1].id,
    ]


@pytest.mark.asyncio
async def test_memberships_return_ordered_by_authoritative_position(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Group reads are ordered by stored position regardless of add order."""
    thread_a, a_issues = await _make_thread(
        async_db, default_user, title="A", issue_count=2, queue_position=94
    )
    thread_b, b_issues = await _make_thread(
        async_db, default_user, title="B", issue_count=2, queue_position=95
    )
    group = await _make_group(async_db, default_user, _unique_name("Ordered"))

    for issue_id in (a_issues[0].id, b_issues[0].id):
        response = await auth_client.post(
            f"/api/v1/reading-order-groups/{group.id}/members",
            json={"issue_id": issue_id},
        )
        assert response.status_code == 201

    pivot = await auth_client.post(
        f"/api/v1/reading-order-groups/{group.id}/members",
        json={"thread_id": thread_a.id},
    )
    assert pivot.status_code == 201
    assert pivot.json()["sequence_order"] == 3

    follow_up = await auth_client.get(f"/api/v1/reading-order-groups/{group.id}")
    assert follow_up.status_code == 200
    lists = await auth_client.get("/api/v1/reading-order-groups/")
    assert lists.status_code == 200

    members = follow_up.json()["memberships"]
    assert [member["sequence_order"] for member in members] == [1, 2, 3]
    listed = next(
        entry for entry in lists.json() if entry["id"] == group.id
    )["memberships"]
    assert [member["sequence_order"] for member in listed] == [1, 2, 3]