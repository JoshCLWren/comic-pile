"""Repair threads whose issue-tracking counters drifted from their issue rows.

Broad materialization passes could publish an external series size as a
thread's reading commitment while adopting only a subset of that series
locally. This reconciliation re-derives the denormalized counters from the
issue rows a thread actually owns. It never mutates read history (issue
status, read timestamps, ratings), never creates or deletes issue rows, and
never changes thread lifecycle status.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import issue_repository, thread_repository
from app.services.issue_tracking import apply_thread_issue_tracking_state


@dataclass(frozen=True)
class ThreadIssueTrackingRepair:
    """Before/after issue-tracking counters for one repaired thread."""

    thread_id: int
    total_issues_before: int | None
    total_issues_after: int
    issues_remaining_before: int
    issues_remaining_after: int
    next_unread_issue_id_before: int | None
    next_unread_issue_id_after: int | None
    reading_progress_before: str | None
    reading_progress_after: str


@dataclass(frozen=True)
class ThreadIssueTrackingReconciliationReport:
    """Outcome of one bounded issue-tracking reconciliation pass."""

    scanned: int
    repaired: int
    committed: bool
    repairs: tuple[ThreadIssueTrackingRepair, ...]


async def reconcile_thread_issue_tracking(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    limit: int | None = None,
    commit: bool = False,
) -> ThreadIssueTrackingReconciliationReport:
    """Re-derive issue-tracking counters for threads that drifted from their rows.

    Args:
        db: Async database session.
        user_id: Optional owner filter for a bounded, per-user pass.
        limit: Optional maximum number of drifted threads to inspect.
        commit: When True, persist the repairs; otherwise roll them back so the
            pass stays a dry run.

    Returns:
        Report describing the threads inspected and the counters rewritten.
    """
    drifted_threads = await thread_repository.fetch_threads_with_drifted_issue_tracking(
        db, user_id=user_id, limit=limit
    )

    repairs: list[ThreadIssueTrackingRepair] = []
    for thread in drifted_threads:
        adopted_issues = await issue_repository.issues_ordered(db, thread.id)
        total_issues_before = thread.total_issues
        issues_remaining_before = thread.issues_remaining
        next_unread_issue_id_before = thread.next_unread_issue_id
        reading_progress_before = thread.reading_progress

        state = apply_thread_issue_tracking_state(thread, adopted_issues)
        if (
            total_issues_before == state.total_issues
            and issues_remaining_before == state.issues_remaining
            and next_unread_issue_id_before == state.next_unread_issue_id
            and reading_progress_before == state.reading_progress
        ):
            continue

        repairs.append(
            ThreadIssueTrackingRepair(
                thread_id=thread.id,
                total_issues_before=total_issues_before,
                total_issues_after=state.total_issues,
                issues_remaining_before=issues_remaining_before,
                issues_remaining_after=state.issues_remaining,
                next_unread_issue_id_before=next_unread_issue_id_before,
                next_unread_issue_id_after=state.next_unread_issue_id,
                reading_progress_before=reading_progress_before,
                reading_progress_after=state.reading_progress,
            )
        )

    if commit:
        await db.commit()
    else:
        await db.rollback()

    return ThreadIssueTrackingReconciliationReport(
        scanned=len(drifted_threads),
        repaired=len(repairs),
        committed=commit,
        repairs=tuple(repairs),
    )
