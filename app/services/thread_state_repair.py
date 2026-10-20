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
from app.repositories import thread_repository
from comic_pile.dependencies import refresh_user_blocked_status


async def _recalculate_thread_state(thread: Thread, issues: list[Issue]) -> bool:
    """Recompute denormalized thread fields from in-memory issues.

    Legacy counter-based threads (``total_issues is None``) keep their
    tracking mode: repairing their lifecycle state must not silently migrate
    them to issue tracking.

    Returns True when the thread transitioned out of completed.
    """
    was_completed = thread.status == "completed"
    unread = [issue for issue in issues if issue.status != "read"]
    unread_count = len(unread)
    total = len(issues)

    if thread.total_issues is not None:
        thread.total_issues = total
    thread.issues_remaining = unread_count
    if unread:
        # Earliest unread by canonical position, then id.
        earliest = min(unread, key=lambda issue: (issue.position, issue.id))
        thread.next_unread_issue_id = earliest.id
        thread.reading_progress = "not_started" if unread_count == total else "in_progress"
        thread.apply_derived_status("active")
    else:
        thread.next_unread_issue_id = None
        thread.reading_progress = "completed"
        thread.apply_derived_status("completed")

    return was_completed and thread.status == "active"


async def _lock_repair_candidates(
    db: AsyncSession,
    *,
    user_id: int | None,
) -> list[Thread]:
    """Return locked repair candidates after taking each owner's queue lock.

    Every queue writer acquires the per-reader queue lock before locking or
    dirtying thread rows. This repair follows the same global lock order:
    identify candidates first, acquire the queue lock for each affected owner,
    and only then lock the candidate thread rows. Locking rows first could
    deadlock against a concurrent queue move that already holds the queue lock
    and is waiting for a row this transaction locked.

    Args:
        db: Async database session.
        user_id: When set, scope candidates to one user.

    Returns:
        Candidate threads locked for repair, ordered by ID.
    """
    return await thread_repository.fetch_locked_repair_candidates_rechecked(
        db, user_id=user_id
    )


async def reconcile_contradictory_completed_threads(
    db: AsyncSession,
    *,
    user_id: int | None = None,
) -> dict[str, object]:
    """Fix threads with ``status=completed`` but positive unread.

    Does not mutate issue read state, ``read_at`` timestamps, or event/rating
    history. Only recomputes ``total_issues``, ``issues_remaining``,
    ``next_unread_issue_id``, ``reading_progress``, ``status``, and blocked
    denormalization via the normal domain path. Legacy counter-based threads
    keep ``total_issues = None``; completing them never migrates them to issue
    tracking.

    Args:
        db: Async database session.
        user_id: When set, scope repair to one user; otherwise repair all users.

    Returns:
        Summary with counts of inspected and repaired threads.
    """
    candidates = await _lock_repair_candidates(db, user_id=user_id)
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
        was_active = thread.status == "active"
        if unread_count == 0:
            # No unread issues: thread must be completed. Repair denormalized
            # counters, status, queue position, and stale blocked flags.
            # Legacy threads keep their counter mode (total_issues stays NULL).
            tracks_issues = thread.total_issues is not None
            expected_total = len(issues) if tracks_issues else thread.total_issues
            denormalized_stale = (
                (tracks_issues and thread.total_issues != expected_total)
                or thread.issues_remaining != 0
                or thread.next_unread_issue_id is not None
                or thread.reading_progress != "completed"
                or thread.is_blocked
                or was_active
            )
            if denormalized_stale:
                if tracks_issues:
                    thread.total_issues = expected_total
                thread.issues_remaining = 0
                thread.next_unread_issue_id = None
                thread.reading_progress = "completed"
                thread.is_blocked = False
                transitioned = thread.apply_derived_status("completed")
                if was_active and transitioned:
                    thread.queue_position = 0
                    await thread_repository.renormalize_queue_positions(db, thread.user_id)
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
