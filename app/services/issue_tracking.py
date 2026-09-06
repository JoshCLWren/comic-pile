"""Derivation of a thread's issue-tracking state from its local issue rows.

Issue-tracking counters (``total_issues``, ``issues_remaining``,
``next_unread_issue_id``, ``reading_progress``) are denormalizations of the
issue rows ComicPile actually tracks for a thread. Materialization paths that
adopt only part of an external series (saved CBL requirements, ComicVine
volumes) must never publish the external series size as a reading commitment,
so every persistence path derives these fields here instead of carrying
externally supplied totals forward.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.models.issue import Issue
from app.models.thread import Thread


@dataclass(frozen=True)
class ThreadIssueTrackingState:
    """Issue-tracking counters derived from the issue rows a thread owns."""

    total_issues: int
    issues_remaining: int
    next_unread_issue_id: int | None
    reading_progress: str


def derive_thread_issue_tracking_state(issues: Sequence[Issue]) -> ThreadIssueTrackingState:
    """Derive issue-tracking counters from locally adopted issue rows.

    Args:
        issues: Every issue row the thread owns, in canonical position order.

    Returns:
        Counters describing only the adopted rows; totals never reflect the
        size of an external series the rows were adopted from.
    """
    unread_issues = [issue for issue in issues if issue.status == "unread"]
    total_issues = len(issues)
    issues_remaining = len(unread_issues)

    if issues_remaining == 0:
        reading_progress = "completed"
    elif issues_remaining == total_issues:
        reading_progress = "not_started"
    else:
        reading_progress = "in_progress"

    return ThreadIssueTrackingState(
        total_issues=total_issues,
        issues_remaining=issues_remaining,
        next_unread_issue_id=unread_issues[0].id if unread_issues else None,
        reading_progress=reading_progress,
    )


def apply_thread_issue_tracking_state(
    thread: Thread, issues: Sequence[Issue]
) -> ThreadIssueTrackingState:
    """Write derived issue-tracking counters onto a thread.

    Lifecycle ``status`` is left to the caller; this function owns only the
    counters and the next-unread pointer.

    Args:
        thread: Thread whose denormalized counters are refreshed.
        issues: Every issue row the thread owns, in canonical position order.

    Returns:
        The derived state that was written onto the thread.
    """
    state = derive_thread_issue_tracking_state(issues)
    thread.total_issues = state.total_issues
    thread.issues_remaining = state.issues_remaining
    thread.next_unread_issue_id = state.next_unread_issue_id
    thread.reading_progress = state.reading_progress
    return state
