"""Repair invalid completed-thread state left by appended unread issues.

Threads may only be ``completed`` when they have zero unread locally tracked
issues. Appending unread issues via the CBL/issue-creation path historically
left ``status = completed`` while ``issues_remaining > 0`` / ``next_unread`` was
stale. This module reconciles that invariant without inferring reads from the
prior completed status and without mutating read timestamps or ratings.

The predicate for unread is issue ``status != 'read'`` — ``read_at IS NULL``
alone is not sufficient for imported historical data where read rows may lack
timestamps.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from comic_pile.dependencies import refresh_user_blocked_status


async def _recalculate_thread_state(thread: Thread, issues: list[Issue]) -> bool:
    """Recompute denormalized thread fields from in-memory issues.

    Returns True when the thread transitioned out of completed.
    """
    was_completed = thread.status == "completed"
    unread = [issue for issue in issues if issue.status != "read"]
    unread_count = len(unread)
    total = len(issues)

    thread.total_issues = total
    thread.issues_remaining = unread_count
    if unread:
        # Earliest unread by canonical position, then id.
        earliest = min(unread, key=lambda issue: (issue.position, issue.id))
        thread.next_unread_issue_id = earliest.id
        thread.reading_progress = "not_started" if unread_count == total else "in_progress"
        thread.status = "active"
    else:
        thread.next_unread_issue_id = None
        thread.reading_progress = "completed"
        thread.status = "completed"

    return was_completed and thread.status == "active"


async def reconcile_contradictory_completed_threads(
    db: AsyncSession,
    *,
    user_id: int | None = None,
) -> dict[str, object]:
    """Fix threads with ``status=completed`` but positive unread.

    Does not mutate issue read state, ``read_at`` timestamps, or event/rating
    history. Only recomputes ``total_issues``, ``issues_remaining``,
    ``next_unread_issue_id``, ``reading_progress``, ``status``, and blocked
    denormalization via the normal domain path.

    Args:
        db: Async database session.
        user_id: When set, scope repair to one user; otherwise repair all users.

    Returns:
        Summary with counts of inspected and repaired threads.
    """
    # Find candidate completed threads with issue tracking enabled.
    query = select(Thread).where(Thread.status == "completed", Thread.total_issues.is_not(None))
    if user_id is not None:
        query = query.where(Thread.user_id == user_id)
    query = query.order_by(Thread.id).with_for_update()

    result = await db.execute(query)
    candidates = list(result.scalars().all())

    inspected = len(candidates)
    repaired = 0
    repaired_ids: list[int] = []
    affected_user_ids: set[int] = set()

    for thread in candidates:
        # Load issues ordered by position; lock rows for consistency.
        issues_result = await db.execute(
            select(Issue)
            .where(Issue.thread_id == thread.id)
            .order_by(Issue.position, Issue.id)
            .with_for_update()
        )
        issues = list(issues_result.scalars().all())
        unread_count = sum(1 for issue in issues if issue.status != "read")
        if unread_count == 0:
            # No contradiction; ensure denormalization agrees (total may be stale).
            expected_total = len(issues)
            if (
                thread.total_issues != expected_total
                or thread.issues_remaining != 0
                or thread.next_unread_issue_id is not None
                or thread.reading_progress != "completed"
            ):
                thread.total_issues = expected_total
                thread.issues_remaining = 0
                thread.next_unread_issue_id = None
                thread.reading_progress = "completed"
                thread.status = "completed"
                repaired += 1
                repaired_ids.append(thread.id)
                affected_user_ids.add(thread.user_id)
            continue

        # Contradiction: completed but unread exists. Recompute via domain path.
        transitioned = await _recalculate_thread_state(thread, issues)
        if transitioned:
            # Shift active queue positions to make room at front, preserving
            # blocked/queue invariants for the domain path. Do this per
            # repaired thread in id order; last repaired ends at position 1
            # with earlier repaired shifted to 2, etc. This matches the
            # create_issues path that would have shifted had the write been
            # correct originally.
            await db.execute(
                update(Thread)
                .where(Thread.user_id == thread.user_id)
                .where(Thread.status == "active")
                .where(Thread.id != thread.id)
                .values(queue_position=Thread.queue_position + 1)
            )
            thread.queue_position = 1

        repaired += 1
        repaired_ids.append(thread.id)
        affected_user_ids.add(thread.user_id)

    # Refresh blocked denormalization for affected users via normal evaluator.
    for uid in affected_user_ids:
        await refresh_user_blocked_status(uid, db)

    await db.flush()

    return {
        "inspected_completed_threads": inspected,
        "repaired_threads": repaired,
        "repaired_thread_ids": repaired_ids,
        "affected_user_ids": sorted(affected_user_ids),
    }
