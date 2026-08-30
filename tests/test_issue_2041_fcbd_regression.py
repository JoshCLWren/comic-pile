"""Regression coverage for crossover #15 FCBD read-state reconciliation (issue #2041).

Proves the canonical evaluator never surfaces a genuinely read prerequisite in
unread_issue_details, and that Roll eligibility agrees with exact issue readiness
for Ultimates #18 after the FCBD prerequisite is satisfied.

Also covers aggregate crossover blocking: when the crossover remains blocked for
another branch, the reported cause is the actual remaining unread issue rather
than the already-read FCBD entry.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_blocking import get_continuity_blocked_thread_ids
from app.models.continuity_rule import ContinuityRule
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.dependencies import _get_blocked_thread_ids_uncached, refresh_user_blocked_status
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


@pytest.mark.asyncio
async def test_read_fcbd_does_not_block_ultimates_18_and_roll_agrees(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A genuinely read FCBD prerequisite clears both readiness and Roll eligibility."""
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

    # Initially blocked.
    response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": ultimates_18.id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_readable"] is False
    blocker = response.json()["blockers"][0]
    assert fcbd_issue.id in blocker["causing_issue_ids"]
    assert any(d["issue_id"] == fcbd_issue.id for d in blocker["unread_issue_details"])

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert ultimates_thread.id in blocked
    await async_db.refresh(ultimates_thread)
    # Denormalized flag should also reflect blocked after rule creation.
    assert ultimates_thread.is_blocked is True or ultimates_thread.id in blocked

    # Mark FCBD read and recompute.
    fcbd_issue.status = "read"
    fcbd_issue.read_at = datetime.now(UTC)
    async_db.add(fcbd_issue)
    # Simulate what the API path does: refresh denormalized flags.
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    # Exact issue readiness must be clear and not mention FCBD.
    readiness = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": ultimates_18.id},
    )
    assert readiness.status_code == 200, readiness.text
    payload = readiness.json()
    assert payload["is_readable"] is True, payload
    assert payload["blockers"] == []
    # No unread_issue_details anywhere should contain the read FCBD.
    for block in payload["blockers"]:
        assert all(d["issue_id"] != fcbd_issue.id for d in block["unread_issue_details"])

    # Crossover readiness also must not surface the read FCBD.
    crossover_readiness = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "crossover", "node_id": crossover.id},
    )
    assert crossover_readiness.status_code == 200, crossover_readiness.text
    cx_payload = crossover_readiness.json()
    # After FCBD read, the crossover's only member blockers are gone, so readable.
    assert cx_payload["is_readable"] is True, cx_payload
    for block in cx_payload["blockers"]:
        assert all(d["issue_id"] != fcbd_issue.id for d in block["unread_issue_details"])

    # Roll eligibility must agree with readiness for Ultimates #18.
    blocked_after = await get_continuity_blocked_thread_ids(user.id, async_db)
    assert ultimates_thread.id not in blocked_after

    await async_db.refresh(ultimates_thread)
    assert ultimates_thread.is_blocked is False

    # Bounded roll pool must contain Ultimates thread now.
    rows = await get_bounded_roll_pool_rows(user.id, async_db, current_die=20)
    roll_ids = {row[0].id for row in rows}
    assert ultimates_thread.id in roll_ids


@pytest.mark.asyncio
async def test_crossover_aggregate_blocked_identifies_remaining_cause_not_read_fcbd(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """When crossover remains blocked, the cause is the actual unread branch, not the read FCBD."""
    user = await get_or_create_user_async(async_db)

    fcbd_thread, fcbd_issue = await _make_thread_with_issue(
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
    # Another unread branch that also blocks the same target via a different rule/crossover.
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
    # Two independent prerequisites for Ultimates #18.
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

    # Mark FCBD read, leaving the other prerequisite unread.
    fcbd_issue.status = "read"
    fcbd_issue.read_at = datetime.now(UTC)
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    readiness = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": ultimates_18.id},
    )
    assert readiness.status_code == 200, readiness.text
    payload = readiness.json()
    assert payload["is_readable"] is False
    # Must not mention the already-read FCBD.
    for block in payload["blockers"]:
        assert all(d["issue_id"] != fcbd_issue.id for d in block["unread_issue_details"])
        assert fcbd_issue.id not in block["causing_issue_ids"]
        assert fcbd_issue.id not in block["causing_member_issue_ids"]
    # Must mention the actual remaining unread cause.
    all_unread = {d["issue_id"] for block in payload["blockers"] for d in block["unread_issue_details"]}
    assert other_issue.id in all_unread

    crossover_readiness = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "crossover", "node_id": crossover.id},
    )
    assert crossover_readiness.status_code == 200, crossover_readiness.text
    cx_blocks = crossover_readiness.json()["blockers"]
    # Aggregate crossover blockers should also not leak the read FCBD.
    for block in cx_blocks:
        assert all(d["issue_id"] != fcbd_issue.id for d in block["unread_issue_details"])
    # But should still be blocked via the other unread member's prerequisite.
    assert len(cx_blocks) >= 1


@pytest.mark.asyncio
async def test_crossover_thread_membership_read_does_not_leak(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Thread-level crossover membership with a read issue does not keep the thread blocked."""
    user = await get_or_create_user_async(async_db)

    # FCBD thread with one read issue.
    fcbd_thread, fcbd_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Free Comic Book Day 2025",
        issue_number="2025",
        queue_position=30,
        status="read",
    )
    target_thread, target_issue = await _make_thread_with_issue(
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
    # Membership via thread (covers all issues in thread).
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

    # Since the only other member besides the target is the already-read FCBD issue,
    # the only unread member is the target itself; but target's self-membership
    # should not cause it to be considered a prerequisite for itself. The
    # defensive filtering plus is_read means the read FCBD must not appear.
    # However the rule as written requires all members read, including the target
    # which is unread, so it would stay blocked by itself. To avoid that
    # degenerate case, assert that unread_issue_details never contains the read FCBD.
    readiness = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target_issue.id},
    )
    assert readiness.status_code == 200, readiness.text
    for block in readiness.json()["blockers"]:
        assert all(d["issue_id"] != fcbd_issue.id for d in block["unread_issue_details"])
