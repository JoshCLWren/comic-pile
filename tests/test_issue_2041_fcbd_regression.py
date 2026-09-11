"""Regression coverage for crossover #15 FCBD prerequisite enforcement (issue #2041).

Proves the canonical evaluator never surfaces a genuinely read prerequisite in
unread_issue_details, and that Roll candidate selection agrees with that
prerequisite state for Ultimates #18.

Also covers aggregate crossover blocking: when the target remains blocked for
another branch, the reported cause is the actual remaining unread issue rather
than the already-read FCBD entry.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.continuity_graph import crossover_readiness, issue_readiness, load_snapshot
from comic_pile.dependencies import _invalidate_continuity_snapshot, refresh_user_blocked_status
from comic_pile.queue import get_bounded_roll_pool_rows
from tests.conftest import get_or_create_user_async


async def _make_thread_with_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    issue_number: str,
    queue_position: int,
    status: str = "unread",
) -> tuple[Thread, Issue]:
    """Create one owned thread with a single issue."""
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
        status=status,
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id if status == "unread" else None
    if status == "read":
        thread.reading_progress = "completed"
        thread.status = "completed"
        thread.issues_remaining = 0
    await db.flush()
    return thread, issue


async def _roll_pool_ids(user_id: int, db: AsyncSession) -> set[int]:
    """Return thread IDs currently eligible for bounded Roll candidate selection."""
    rows = await get_bounded_roll_pool_rows(user_id, db, current_die=20)
    return {row[0].id for row in rows}


async def _issue_blockers(user_id: int, db: AsyncSession, issue_id: int):
    """Return canonical hard-prerequisite blockers for one issue."""
    _invalidate_continuity_snapshot(user_id, db)
    snapshot = await load_snapshot(db, user_id)
    return issue_readiness(issue_id, snapshot)


async def _crossover_blockers(user_id: int, db: AsyncSession, group_id: int):
    """Return canonical blockers aggregated for one crossover."""
    _invalidate_continuity_snapshot(user_id, db)
    snapshot = await load_snapshot(db, user_id)
    return crossover_readiness(group_id, snapshot)


@pytest.mark.asyncio
async def test_unread_fcbd_excludes_ultimates_18_from_roll_until_satisfied(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Unread FCBD keeps Ultimates #18 out of Roll; satisfying it restores eligibility."""
    user = await get_or_create_user_async(async_db)

    fcbd_thread, fcbd_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Free Comic Book Day 2025",
        issue_number="1",
        queue_position=10,
        status="unread",
    )
    ultimates_thread, ultimates_18 = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="The Ultimates",
        issue_number="18",
        queue_position=11,
        status="unread",
    )
    # Crossover #15 Ultimate Universe containing both entries.
    crossover = DependencyGroup(user_id=user.id, name="Ultimate Universe")
    async_db.add(crossover)
    await async_db.flush()
    async_db.add(DependencyGroupMembership(group_id=crossover.id, issue_id=fcbd_issue.id))
    async_db.add(DependencyGroupMembership(group_id=crossover.id, issue_id=ultimates_18.id))
    # Rule: FCBD must be read before Ultimates #18.
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=fcbd_issue.id,
            target_type="issue",
            target_id=ultimates_18.id,
            satisfaction_type="item_read",
        )
    )
    await async_db.commit()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blockers = await _issue_blockers(user.id, async_db, ultimates_18.id)
    assert blockers, "unread FCBD must remain a hard prerequisite"
    assert fcbd_issue.id in blockers[0].causing_issue_ids
    assert any(detail.issue_id == fcbd_issue.id for detail in blockers[0].unread_issue_details)

    roll_ids = await _roll_pool_ids(user.id, async_db)
    assert fcbd_thread.id in roll_ids
    assert ultimates_thread.id not in roll_ids

    rolled = await auth_client.post("/api/v1/roll/")
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["thread_id"] != ultimates_thread.id

    blocked_override = await auth_client.post(
        "/api/v1/roll/override", json={"thread_id": ultimates_thread.id}
    )
    assert blocked_override.status_code == 422
    assert "blocked" in blocked_override.json()["detail"].lower()

    fcbd_issue.status = "read"
    fcbd_issue.read_at = datetime.now(UTC)
    async_db.add(fcbd_issue)
    fcbd_thread.status = "completed"
    fcbd_thread.reading_progress = "completed"
    fcbd_thread.issues_remaining = 0
    fcbd_thread.next_unread_issue_id = None
    async_db.add(fcbd_thread)
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blockers_after = await _issue_blockers(user.id, async_db, ultimates_18.id)
    assert blockers_after == []
    for blocker in blockers_after:
        assert all(detail.issue_id != fcbd_issue.id for detail in blocker.unread_issue_details)

    crossover_blockers = await _crossover_blockers(user.id, async_db, crossover.id)
    for blocker in crossover_blockers:
        assert all(detail.issue_id != fcbd_issue.id for detail in blocker.unread_issue_details)

    await async_db.refresh(ultimates_thread)
    assert ultimates_thread.is_blocked is False

    roll_ids_after = await _roll_pool_ids(user.id, async_db)
    assert ultimates_thread.id in roll_ids_after
    assert fcbd_thread.id not in roll_ids_after

    await auth_client.post("/api/v1/roll/dismiss-pending")
    rolled_after = await auth_client.post("/api/v1/roll/")
    assert rolled_after.status_code == 200, rolled_after.text
    assert rolled_after.json()["thread_id"] == ultimates_thread.id


@pytest.mark.asyncio
async def test_crossover_aggregate_blocked_identifies_remaining_cause_not_read_fcbd(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """When the target remains blocked, the cause is the unread branch, not read FCBD."""
    user = await get_or_create_user_async(async_db)

    _fcbd_thread, fcbd_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Free Comic Book Day 2025",
        issue_number="1",
        queue_position=20,
        status="unread",
    )
    ultimates_thread, ultimates_18 = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="The Ultimates",
        issue_number="18",
        queue_position=21,
        status="unread",
    )
    # Another unread branch that also blocks the same target via a different rule.
    other_thread, other_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Ultimate Black Panther",
        issue_number="5",
        queue_position=22,
        status="unread",
    )
    crossover = DependencyGroup(user_id=user.id, name="Ultimate Universe")
    async_db.add(crossover)
    await async_db.flush()
    for issue in (fcbd_issue, ultimates_18, other_issue):
        async_db.add(DependencyGroupMembership(group_id=crossover.id, issue_id=issue.id))
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=fcbd_issue.id,
            target_type="issue",
            target_id=ultimates_18.id,
            satisfaction_type="item_read",
        )
    )
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=other_issue.id,
            target_type="issue",
            target_id=ultimates_18.id,
            satisfaction_type="item_read",
        )
    )
    await async_db.commit()

    fcbd_issue.status = "read"
    fcbd_issue.read_at = datetime.now(UTC)
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blockers = await _issue_blockers(user.id, async_db, ultimates_18.id)
    assert blockers, "remaining unread prerequisite must still block Ultimates #18"
    for blocker in blockers:
        assert all(detail.issue_id != fcbd_issue.id for detail in blocker.unread_issue_details)
        assert fcbd_issue.id not in blocker.causing_issue_ids
        assert fcbd_issue.id not in blocker.causing_member_issue_ids
    all_unread = {detail.issue_id for blocker in blockers for detail in blocker.unread_issue_details}
    assert other_issue.id in all_unread

    roll_ids = await _roll_pool_ids(user.id, async_db)
    assert ultimates_thread.id not in roll_ids
    assert other_thread.id in roll_ids

    blocked_override = await auth_client.post(
        "/api/v1/roll/override", json={"thread_id": ultimates_thread.id}
    )
    assert blocked_override.status_code == 422

    crossover_blockers = await _crossover_blockers(user.id, async_db, crossover.id)
    assert crossover_blockers
    for blocker in crossover_blockers:
        assert all(detail.issue_id != fcbd_issue.id for detail in blocker.unread_issue_details)


@pytest.mark.asyncio
async def test_crossover_thread_membership_read_does_not_leak(
    async_db: AsyncSession,
) -> None:
    """Thread-level crossover membership with a read issue does not leak as a blocker."""
    user = await get_or_create_user_async(async_db)

    fcbd_thread, fcbd_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Free Comic Book Day 2025",
        issue_number="2025",
        queue_position=30,
        status="read",
    )
    _target_thread, target_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="The Ultimates",
        issue_number="18",
        queue_position=31,
        status="unread",
    )
    crossover = DependencyGroup(user_id=user.id, name="Ultimate Universe")
    async_db.add(crossover)
    await async_db.flush()
    async_db.add(DependencyGroupMembership(group_id=crossover.id, thread_id=fcbd_thread.id))
    async_db.add(DependencyGroupMembership(group_id=crossover.id, issue_id=target_issue.id))
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="crossover",
            source_id=crossover.id,
            target_type="issue",
            target_id=target_issue.id,
            satisfaction_type="all_members_read",
        )
    )
    await async_db.commit()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blockers = await _issue_blockers(user.id, async_db, target_issue.id)
    for blocker in blockers:
        assert all(detail.issue_id != fcbd_issue.id for detail in blocker.unread_issue_details)
        assert fcbd_issue.id not in blocker.causing_issue_ids
        assert fcbd_issue.id not in blocker.causing_member_issue_ids

    roll_ids = await _roll_pool_ids(user.id, async_db)
    assert fcbd_thread.id not in roll_ids
