"""Regression coverage for FCBD prerequisite enforcement (issue #2041).

Proves the canonical evaluator never surfaces a genuinely read prerequisite
in blocker explanations, and that Roll candidate selection agrees with that
prerequisite state for Ultimates #18.

Also covers aggregate blocking: when the target remains blocked for another
branch, the reported cause is the actual remaining unread issue rather than
the already-read FCBD entry.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.dependencies import get_blocking_explanations, refresh_user_blocked_status
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
    # Canonical edge: FCBD must be read before Ultimates #18.
    async_db.add(
        Dependency(
            source_issue_id=fcbd_issue.id,
            target_issue_id=ultimates_18.id,
            note="canonical prerequisite",
        )
    )
    await async_db.commit()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    explanations = await get_blocking_explanations(ultimates_thread.id, user.id, async_db)
    assert explanations, "unread FCBD must remain a hard prerequisite"
    assert all(dep.issue_number == "1" for dep in explanations)
    assert all("Free Comic Book Day 2025" in dep.label for dep in explanations)

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

    # The read prerequisite must not leak into blocker explanations.
    explanations_after = await get_blocking_explanations(
        ultimates_thread.id, user.id, async_db
    )
    assert explanations_after == []

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
async def test_aggregate_blocked_identifies_remaining_cause_not_read_fcbd(
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
    # Another unread branch that also blocks the same target via a different edge.
    other_thread, other_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Ultimate Black Panther",
        issue_number="5",
        queue_position=22,
        status="unread",
    )
    async_db.add(
        Dependency(
            source_issue_id=fcbd_issue.id,
            target_issue_id=ultimates_18.id,
        )
    )
    async_db.add(
        Dependency(
            source_issue_id=other_issue.id,
            target_issue_id=ultimates_18.id,
        )
    )
    await async_db.commit()

    fcbd_issue.status = "read"
    fcbd_issue.read_at = datetime.now(UTC)
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    explanations = await get_blocking_explanations(ultimates_thread.id, user.id, async_db)
    assert explanations, "remaining unread prerequisite must still block Ultimates #18"
    # The read FCBD entry must not leak into the reported causes.
    assert all("Free Comic Book Day" not in dep.label for dep in explanations)
    assert any("Ultimate Black Panther" in dep.label for dep in explanations)

    roll_ids = await _roll_pool_ids(user.id, async_db)
    assert ultimates_thread.id not in roll_ids
    assert other_thread.id in roll_ids

    blocked_override = await auth_client.post(
        "/api/v1/roll/override", json={"thread_id": ultimates_thread.id}
    )
    assert blocked_override.status_code == 422


@pytest.mark.asyncio
async def test_read_prerequisite_never_reported_as_blocker(
    async_db: AsyncSession,
) -> None:
    """A read source issue never appears in blocker explanations."""
    user = await get_or_create_user_async(async_db)

    _fcbd_thread, fcbd_issue = await _make_thread_with_issue(
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
    async_db.add(
        Dependency(
            source_issue_id=fcbd_issue.id,
            target_issue_id=target_issue.id,
        )
    )
    await async_db.commit()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    assert await get_blocking_explanations(target_thread.id, user.id, async_db) == []

    roll_ids = await _roll_pool_ids(user.id, async_db)
    assert target_thread.id in roll_ids
