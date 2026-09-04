"""Reusable issue-order and thread tracking state helpers."""

from app.models.issue import Issue
from app.models.thread import Thread


def recalculate_next_unread_issue_id(thread: Thread, issues: list[Issue]) -> None:
    """Update a thread's next unread pointer from canonical issue order."""
    next_unread = next((issue for issue in issues if issue.status == "unread"), None)
    thread.next_unread_issue_id = next_unread.id if next_unread else None


def recalculate_thread_issue_tracking_state(thread: Thread, issues: list[Issue]) -> None:
    """Recalculate thread counters and progress without changing issue history."""
    unread = [issue for issue in issues if issue.status == "unread"]
    thread.total_issues = len(issues)
    thread.issues_remaining = len(unread)
    thread.next_unread_issue_id = unread[0].id if unread else None

    if not unread:
        thread.reading_progress = "completed"
        thread.status = "completed"
    else:
        thread.reading_progress = "not_started" if len(unread) == len(issues) else "in_progress"
        if thread.status == "completed":
            thread.status = "active"
