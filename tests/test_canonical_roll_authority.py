"""Acceptance coverage for canonical Thread-frontier plus Dependency Roll authority.

Issue #2553 collapses Roll eligibility onto the frozen canonical runtime:

    Thread.next_unread_issue_id + incoming canonical Dependency rows = Roll eligibility

The cases below mirror the issue acceptance list, using the Starman #55 shape and
the X-Men/Cable crossover shape recorded in
``docs/READING_GRAPH_RUNTIME_AUDIT.md`` sections 6.1-6.4.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.dependencies import (
    _get_blocked_thread_ids_uncached,
    get_blocking_explanations,
    refresh_user_blocked_status,
)
from comic_pile.queue import get_roll_pool
from tests.conftest import get_or_create_user_async


@pytest.fixture(autouse=True)
async def _isolate_canonical_edges(async_db: AsyncSession) -> AsyncIterator[None]:
    """Clear persisted Dependency rows and blocked flags left by earlier tests.

    The shared ``async_db`` fixture rolls its truncation back, so rows from an
    earlier test in this module stay visible to the next one. Recreating threads
    and issues then reuses the same surrogate keys, and a leftover edge can block
    a frontier the current test just created. Resetting both tables keeps every
    case below independent of execution order.
    """
    await async_db.execute(delete(Dependency))
    await async_db.execute(update(Thread).values(is_blocked=False))
    await async_db.commit()
    yield


async def _frontier_thread(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    issue_count: int = 1,
) -> tuple[Thread, list[Issue]]:
    """Create an active thread whose frontier is its first unread issue."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=queue_position,
        status="active",
        total_issues=issue_count,
        issues_remaining=issue_count,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status="unread",
        )
        for position in range(1, issue_count + 1)
    ]
    db.add_all(issues)
    await db.flush()
    thread.next_unread_issue_id = issues[0].id
    return thread, issues


async def _roll_thread_ids(user_id: int, db: AsyncSession) -> set[int]:
    return {thread.id for thread in await get_roll_pool(user_id, db)}


@pytest.mark.asyncio
async def test_explicit_prerequisite_gates_the_intended_starting_issue(
    async_db: AsyncSession,
) -> None:
    """A standalone reader prerequisite blocks the frontier it gates."""
    user = await get_or_create_user_async(async_db)
    starman_thread, starman_issues = await _frontier_thread(
        async_db, user_id=user.id, title="Starman", queue_position=1
    )
    jsa_thread, jsa_issues = await _frontier_thread(
        async_db, user_id=user.id, title="JSA All-Star", queue_position=2
    )
    async_db.add(
        Dependency(
            source_issue_id=starman_issues[-1].id,
            target_issue_id=jsa_issues[0].id,
            note="Launch the Robinson/Goyer/Johns JSA path alongside Starman #55.",
        )
    )
    await async_db.commit()

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert jsa_thread.id in blocked
    assert starman_thread.id not in blocked

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    roll_ids = await _roll_thread_ids(user.id, async_db)
    assert jsa_thread.id not in roll_ids
    assert starman_thread.id in roll_ids

    starman_issues[-1].status = "read"
    starman_issues[-1].read_at = datetime.now(UTC)
    starman_thread.issues_remaining = 0
    starman_thread.next_unread_issue_id = None
    await async_db.commit()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    assert jsa_thread.id not in await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert jsa_thread.id in await _roll_thread_ids(user.id, async_db)


@pytest.mark.asyncio
async def test_two_unread_prerequisites_block_until_both_are_read(
    async_db: AsyncSession,
) -> None:
    """Multiple incoming canonical edges require every prerequisite, like ``converged``."""
    user = await get_or_create_user_async(async_db)
    _prereq_a_thread, prereq_a_issues = await _frontier_thread(
        async_db, user_id=user.id, title="Prerequisite A", queue_position=1
    )
    _prereq_b_thread, prereq_b_issues = await _frontier_thread(
        async_db, user_id=user.id, title="Prerequisite B", queue_position=2
    )
    target_thread, target_issues = await _frontier_thread(
        async_db, user_id=user.id, title="Convergence target", queue_position=3
    )
    async_db.add_all(
        [
            Dependency(
                source_issue_id=prereq_a_issues[0].id,
                target_issue_id=target_issues[0].id,
                note="continuity-plan:21",
            ),
            Dependency(
                source_issue_id=prereq_b_issues[0].id,
                target_issue_id=target_issues[0].id,
                note="continuity-plan:21",
            ),
        ]
    )
    await async_db.commit()

    assert target_thread.id in await _get_blocked_thread_ids_uncached(user.id, async_db)
    reasons = await get_blocking_explanations(target_thread.id, user.id, async_db)
    assert sorted(reason.label for reason in reasons) == [
        "Blocked by Prerequisite A: #1",
        "Blocked by Prerequisite B: #1",
    ]

    prereq_a_issues[0].status = "read"
    prereq_a_issues[0].read_at = datetime.now(UTC)
    await async_db.commit()
    assert target_thread.id in await _get_blocked_thread_ids_uncached(user.id, async_db)

    prereq_b_issues[0].status = "read"
    prereq_b_issues[0].read_at = datetime.now(UTC)
    await async_db.commit()
    assert target_thread.id not in await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert await get_blocking_explanations(target_thread.id, user.id, async_db) == []


@pytest.mark.asyncio
async def test_same_thread_progression_needs_no_dependency_rows(
    async_db: AsyncSession,
) -> None:
    """Ordinary advancement comes from ``Issue.position`` and the frontier alone."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _frontier_thread(
        async_db,
        user_id=user.id,
        title="X-Men",
        queue_position=1,
        issue_count=3,
    )
    await async_db.commit()

    assert thread.id not in await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert thread.id in await _roll_thread_ids(user.id, async_db)

    # Advance the frontier to the second issue; still no adjacency rows exist.
    issues[0].status = "read"
    issues[0].read_at = datetime.now(UTC)
    thread.next_unread_issue_id = issues[1].id
    thread.issues_remaining = 2
    await async_db.commit()

    assert thread.id not in await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert await get_blocking_explanations(thread.id, user.id, async_db) == []


@pytest.mark.asyncio
async def test_historical_cbl_rows_never_gate_a_frontier(
    async_db: AsyncSession,
) -> None:
    """Neither ``cbl-order:source:*`` nor ``cbl-order:group-16:*`` blocks Roll."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _frontier_thread(
        async_db, user_id=user.id, title="CBL source", queue_position=1
    )
    adjacency_threads: list[Thread] = []
    for queue_position, note in (
        (2, "cbl-order:source:90520"),
        (3, "cbl-order:group-16:1228"),
    ):
        target_thread, target_issues = await _frontier_thread(
            async_db,
            user_id=user.id,
            title=f"CBL adjacency {queue_position}",
            queue_position=queue_position,
        )
        adjacency_threads.append(target_thread)
        async_db.add(
            Dependency(
                source_issue_id=source_issues[0].id,
                target_issue_id=target_issues[0].id,
                note=note,
            )
        )
        await async_db.flush()
        assert target_thread.id not in await _get_blocked_thread_ids_uncached(
            user.id, async_db
        )
        assert await get_blocking_explanations(target_thread.id, user.id, async_db) == []

    await async_db.commit()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    roll_ids = await _roll_thread_ids(user.id, async_db)
    assert {thread.id for thread in adjacency_threads} <= roll_ids


@pytest.mark.asyncio
async def test_crossover_prerequisites_still_block_canonically(
    async_db: AsyncSession,
) -> None:
    """Explicit X-Men / Cable / X-Force prerequisite edges survive the cutover."""
    user = await get_or_create_user_async(async_db)
    titles = [
        "Generation X #48",
        "Cable #64",
        "Uncanny X-Men #365",
        "Uncanny X-Men #372",
        "Cable #71",
        "X-Force #101",
    ]
    created = [
        await _frontier_thread(
            async_db,
            user_id=user.id,
            title=title,
            queue_position=position,
        )
        for position, title in enumerate(titles, start=1)
    ]
    issues = {thread.title: thread_issues[0] for thread, thread_issues in created}
    threads = {thread.title: thread for thread, _ in created}

    async_db.add_all(
        [
            Dependency(
                source_issue_id=issues["Generation X #48"].id,
                target_issue_id=issues["Cable #64"].id,
                note="UXRO Era Ten",
            ),
            Dependency(
                source_issue_id=issues["Cable #64"].id,
                target_issue_id=issues["Uncanny X-Men #365"].id,
                note="UXRO Era Ten",
            ),
            Dependency(
                source_issue_id=issues["Cable #71"].id,
                target_issue_id=issues["Uncanny X-Men #372"].id,
                note="UXRO Era Ten",
            ),
            Dependency(
                source_issue_id=issues["Uncanny X-Men #372"].id,
                target_issue_id=issues["X-Force #101"].id,
                note="UXRO Era Ten",
            ),
        ]
    )
    await async_db.commit()

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert blocked == {
        threads["Cable #64"].id,
        threads["Uncanny X-Men #365"].id,
        threads["Uncanny X-Men #372"].id,
        threads["X-Force #101"].id,
    }

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    roll_ids = await _roll_thread_ids(user.id, async_db)
    assert threads["Uncanny X-Men #365"].id not in roll_ids
    assert threads["X-Force #101"].id not in roll_ids
    assert threads["Generation X #48"].id in roll_ids


@pytest.mark.asyncio
async def test_explanations_agree_with_eligibility_for_every_pool_thread(
    async_db: AsyncSession,
) -> None:
    """Reader-facing explanations never describe a blocker Roll would not enforce."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _frontier_thread(
        async_db, user_id=user.id, title="Explained source", queue_position=1
    )
    explained_thread, explained_issues = await _frontier_thread(
        async_db, user_id=user.id, title="Explained target", queue_position=2
    )
    unexplained_thread, unexplained_issues = await _frontier_thread(
        async_db, user_id=user.id, title="Unexplained target", queue_position=3
    )
    async_db.add_all(
        [
            Dependency(
                source_issue_id=source_issues[0].id,
                target_issue_id=explained_issues[0].id,
                note="genuine standalone prerequisite",
            ),
            Dependency(
                source_issue_id=source_issues[0].id,
                target_issue_id=unexplained_issues[0].id,
                note="cbl-order:source:1",
            ),
        ]
    )
    await async_db.commit()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    for thread in (explained_thread, unexplained_thread):
        reasons = await get_blocking_explanations(thread.id, user.id, async_db)
        assert bool(reasons) is (thread.id in blocked)
        await async_db.refresh(thread)
        assert thread.is_blocked is (thread.id in blocked)
