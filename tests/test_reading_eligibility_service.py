"""Candidate selection preserves Option E constraints before caller weighting."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.collection_exclusion import CollectionExclusion
from app.services.reading_eligibility_service import (
    build_eligibility_snapshot,
    load_eligibility_snapshot,
)
from app.services.reading_list_cycle_validator import ReadingCycleError
from app.services.reading_list_evaluator import (
    ReadingIssue,
    ReadingList,
    ReadingListEntry,
    ReadingPrerequisite,
    ReadingSnapshot,
    ReadingThread,
)


def test_candidate_filters_preserve_strict_order_and_empty_allowed_set() -> None:
    """Caller filters cannot reveal a blocked successor or expand an empty pool."""
    snapshot = ReadingSnapshot(
        1,
        threads=(ReadingThread(1), ReadingThread(2), ReadingThread(3)),
        issues=(ReadingIssue(10, 1, 1), ReadingIssue(20, 2, 1), ReadingIssue(30, 3, 1)),
        lists=(ReadingList(1, "strict", (ReadingListEntry(10), ReadingListEntry(20))),),
    )
    result = build_eligibility_snapshot(snapshot, queued_thread_ids=frozenset({1, 2, 3}))
    assert result.candidate_ids() == {1, 3}
    assert result.candidate_ids(allowed_thread_ids=frozenset()) == set()
    assert result.candidate_ids(allowed_thread_ids=frozenset({2})) == set()
    assert result.candidate_ids(excluded_thread_ids=frozenset({1})) == {3}
    assert result.threads[2].blockers[0].waiting_on_issue_ids == (10,)


def test_frontier_exclusions_activity_and_queue_membership() -> None:
    """Paused, completed, empty and unqueued Threads never enter the candidate pool."""
    snapshot = ReadingSnapshot(
        1,
        threads=(
            ReadingThread(1),
            ReadingThread(2, "paused"),
            ReadingThread(3, "completed"),
            ReadingThread(4),
            ReadingThread(5),
        ),
        issues=(
            ReadingIssue(10, 1, 1),
            ReadingIssue(11, 1, 2),
            ReadingIssue(20, 2, 1),
            ReadingIssue(30, 3, 1),
            ReadingIssue(50, 5, 1),
        ),
        excluded_issue_ids=frozenset({10}),
    )
    result = build_eligibility_snapshot(snapshot, queued_thread_ids=frozenset({1, 2, 3, 4}))
    assert result.candidate_ids() == {1}
    assert result.threads[1].next_issue_id == 11
    assert not result.threads[4].eligible


def test_inactive_prerequisite_source_still_blocks_active_target() -> None:
    """An unread source in a paused Thread retains its concrete blocker provenance."""
    snapshot = ReadingSnapshot(
        1,
        threads=(ReadingThread(1, "paused"), ReadingThread(2)),
        issues=(ReadingIssue(10, 1, 1), ReadingIssue(20, 2, 1)),
        prerequisites=(ReadingPrerequisite(7, 10, 20, "reader", ("reader-authored",)),),
    )
    result = build_eligibility_snapshot(snapshot, queued_thread_ids=frozenset({1, 2}))
    assert result.candidate_ids() == set()
    assert result.threads[2].blockers[0].prerequisite_id == 7
    assert result.threads[2].blockers[0].provenance == ("reader-authored",)


def test_cycle_is_rejected_before_any_candidate_is_returned() -> None:
    """A cyclic graph cannot silently produce a partial eligible pool."""
    snapshot = ReadingSnapshot(
        1,
        threads=(ReadingThread(1), ReadingThread(2)),
        issues=(ReadingIssue(10, 1, 1), ReadingIssue(20, 2, 1)),
        prerequisites=(ReadingPrerequisite(1, 10, 20), ReadingPrerequisite(2, 20, 10)),
    )
    with pytest.raises(ReadingCycleError):
        build_eligibility_snapshot(snapshot, queued_thread_ids=frozenset({1, 2}))


async def test_loader_ignores_stale_cache_and_keeps_other_readers_out(
    async_db: AsyncSession,
) -> None:
    """Real SQL uses natural frontier/exclusions instead of stored blocked state."""
    owner = User(username="live_eligibility_owner", password_hash="unused")
    other = User(username="live_eligibility_other", password_hash="unused")
    async_db.add_all([owner, other])
    await async_db.flush()
    thread = Thread(
        user_id=owner.id,
        title="Owned",
        format="Comic",
        status="active",
        queue_position=1,
        is_blocked=True,
        issues_remaining=0,
    )
    foreign = Thread(
        user_id=other.id,
        title="Foreign",
        format="Comic",
        status="active",
        queue_position=1,
    )
    async_db.add_all([thread, foreign])
    await async_db.flush()
    first = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    second = Issue(thread_id=thread.id, issue_number="2", position=2, status="unread")
    foreign_issue = Issue(thread_id=foreign.id, issue_number="1", position=1, status="unread")
    async_db.add_all([first, second, foreign_issue])
    await async_db.flush()
    thread.next_unread_issue_id = first.id
    async_db.add(CollectionExclusion(user_id=owner.id, issue_id=first.id))
    await async_db.flush()

    result = await load_eligibility_snapshot(async_db, owner.id)

    assert result.candidate_ids() == {thread.id}
    assert result.threads[thread.id].next_issue_id == second.id
    assert foreign.id not in result.threads
    assert thread.is_blocked is True
    assert thread.next_unread_issue_id == first.id
