"""Canonical Roll cutover acceptance regression tests (#2553).

Focused coverage for the acceptance cases the existing suites do not yet
directly prove against the canonical evaluator:

1. A target with two unread canonical prerequisites -- the ADR's ``converged``
   reduction to multiple incoming Dependencies -- stays blocked until BOTH
   source Issues are read, with reader-facing explanations that agree with
   eligibility at every step.
2. Normal same-Thread progression advances through ``Issue.position`` /
   ``Thread.next_unread_issue_id`` without any adjacent Dependency row.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.dependencies import (
    _get_blocked_thread_ids_uncached,
    format_blocking_reason,
    get_blocking_explanations,
    get_blocking_explanations_batch,
    refresh_user_blocked_status,
)
from comic_pile.queue import get_bounded_roll_pool_rows
from tests.conftest import get_or_create_user_async


async def _make_series(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    numbers: Sequence[str],
    queue_position: int,
) -> tuple[Thread, list[Issue]]:
    """Create one owned Thread with ordered unread issues and a consistent frontier.

    Args:
        db: Async database session.
        user_id: Owning user.
        title: Thread title.
        numbers: Issue numbers in natural series order.
        queue_position: Queue ordering for the thread.

    Returns:
        The thread and its ordered issues.
    """
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=len(numbers),
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        total_issues=len(numbers),
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issues: list[Issue] = []
    for position, number in enumerate(numbers, start=1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=number,
            position=position,
            status="unread",
        )
        db.add(issue)
        await db.flush()
        issues.append(issue)
    thread.next_unread_issue_id = issues[0].id
    await db.flush()
    return thread, issues


async def _mark_read(db: AsyncSession, thread: Thread, issue: Issue) -> None:
    """Mark one issue read and advance the thread frontier like the read API.

    Args:
        db: Async database session.
        thread: Thread owning the issue.
        issue: Issue to mark read.
    """
    issue.status = "read"
    issue.read_at = datetime.now(UTC)
    remaining_issues = (
        (
            await db.execute(
                select(Issue.id)
                .where(Issue.thread_id == thread.id)
                .where(Issue.status == "unread")
                .order_by(Issue.position)
            )
        )
        .scalars()
        .all()
    )
    thread.next_unread_issue_id = remaining_issues[0] if remaining_issues else None
    thread.issues_remaining = len(remaining_issues)
    thread.reading_progress = "in_progress" if remaining_issues else "completed"
    await db.flush()


async def _roll_ids(user_id: int, db: AsyncSession) -> set[int]:
    """Return currently Roll-eligible thread ids in the bounded pool.

    Args:
        user_id: Thread owner.
        db: Async database session.

    Returns:
        Eligible thread ids after refreshing denormalized blocked flags.
    """
    await refresh_user_blocked_status(user_id, db)
    rows = await get_bounded_roll_pool_rows(user_id, db, current_die=20)
    return {row[0].id for row in rows}


async def _canonical_dependency_count(db: AsyncSession) -> int:
    """Return the total number of Dependency rows in the isolated test schema.

    Args:
        db: Async database session.

    Returns:
        Dependency row count.
    """
    return int((await db.execute(select(func.count()).select_from(Dependency))).scalar_one())


@pytest.mark.asyncio
async def test_two_unread_prerequisites_block_until_both_are_read(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A target with two unread canonical prerequisites stays blocked until both read.

    The ADR reduces ``converged`` semantics to multiple incoming Dependencies:
    both edges must be satisfied before the target frontier is Roll-eligible.
    One edge uses a standalone NULL note and one uses the write-path compiled
    note form, so both canonical note classes are exercised.
    """
    user = await get_or_create_user_async(async_db)
    alpha_thread, alpha_issues = await _make_series(
        async_db, user_id=user.id, title="Prereq Alpha", numbers=["1"], queue_position=1
    )
    beta_thread, beta_issues = await _make_series(
        async_db, user_id=user.id, title="Prereq Beta", numbers=["1"], queue_position=2
    )
    target_thread, target_issues = await _make_series(
        async_db, user_id=user.id, title="Converged Target", numbers=["1"], queue_position=3
    )
    target_issue = target_issues[0]
    async_db.add_all(
        [
            Dependency(
                source_issue_id=alpha_issues[0].id,
                target_issue_id=target_issue.id,
                note=None,
            ),
            Dependency(
                source_issue_id=beta_issues[0].id,
                target_issue_id=target_issue.id,
                note="canonical:rule:4242",
            ),
        ]
    )
    await async_db.commit()

    # Both prerequisites unread: blocked, excluded from Roll, explained by both.
    blocked_ids = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked_ids
    assert alpha_thread.id not in blocked_ids
    assert beta_thread.id not in blocked_ids

    roll_ids = await _roll_ids(user.id, async_db)
    assert {alpha_thread.id, beta_thread.id} <= roll_ids
    assert target_thread.id not in roll_ids

    both_labels = sorted(
        [
            "Blocked by Prereq Alpha: #1",
            "Blocked by Prereq Beta: #1",
        ]
    )
    reasons = await get_blocking_explanations(target_thread.id, user.id, async_db)
    assert sorted(format_blocking_reason(dep) for dep in reasons) == both_labels
    batched = await get_blocking_explanations_batch(
        [target_thread.id], user.id, async_db
    )
    assert sorted(
        format_blocking_reason(dep) for dep in batched[target_thread.id]
    ) == both_labels

    info = await auth_client.post(f"/api/v1/threads/{target_thread.id}:getBlockingInfo")
    assert info.status_code == 200, info.text
    payload = info.json()
    assert payload["is_blocked"] is True
    assert sorted(payload["blocking_reasons"]) == both_labels
    assert sorted(
        (row["thread_title"], row["issue_number"])
        for row in payload["blocking_dependencies"]
    ) == sorted([("Prereq Alpha", "1"), ("Prereq Beta", "1")])

    # Reading only the first prerequisite keeps the target blocked, and the
    # remaining blocker is the only explanation left.
    await _mark_read(async_db, alpha_thread, alpha_issues[0])
    await async_db.commit()

    blocked_ids = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked_ids
    roll_ids = await _roll_ids(user.id, async_db)
    assert target_thread.id not in roll_ids
    reasons = await get_blocking_explanations(target_thread.id, user.id, async_db)
    assert [format_blocking_reason(dep) for dep in reasons] == ["Blocked by Prereq Beta: #1"]

    # Reading the second prerequisite satisfies both incoming edges.
    await _mark_read(async_db, beta_thread, beta_issues[0])
    await async_db.commit()

    blocked_ids = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id not in blocked_ids
    roll_ids = await _roll_ids(user.id, async_db)
    assert target_thread.id in roll_ids
    assert await get_blocking_explanations(target_thread.id, user.id, async_db) == []

    info = await auth_client.post(f"/api/v1/threads/{target_thread.id}:getBlockingInfo")
    assert info.status_code == 200, info.text
    assert info.json()["is_blocked"] is False
    assert info.json()["blocking_reasons"] == []


@pytest.mark.asyncio
async def test_same_thread_progression_needs_no_dependency_rows(
    async_db: AsyncSession,
) -> None:
    """Natural series advance uses position/frontier with zero adjacent edges.

    A multi-issue Thread must advance frontier by frontier and stay
    Roll-eligible at every step without any Dependency row existing, per the
    ADR rule that natural adjacency is never materialized.
    """
    user = await get_or_create_user_async(async_db)
    thread, issues = await _make_series(
        async_db, user_id=user.id, title="Natural Series", numbers=["1", "2", "3"],
        queue_position=1,
    )
    await async_db.commit()

    assert await _canonical_dependency_count(async_db) == 0

    for index, issue in enumerate(issues):
        blocked_ids = await _get_blocked_thread_ids_uncached(user.id, async_db)
        assert thread.id not in blocked_ids
        roll_ids = await _roll_ids(user.id, async_db)
        assert thread.id in roll_ids
        assert thread.next_unread_issue_id == issue.id
        assert await get_blocking_explanations(thread.id, user.id, async_db) == []
        await _mark_read(async_db, thread, issue)
        await async_db.commit()
        assert await _canonical_dependency_count(async_db) == 0, (
            f"adjacent Dependency row appeared after advancing past position {index + 1}"
        )

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.refresh(thread)
    assert thread.next_unread_issue_id is None
    assert thread.is_blocked is False
