"""Regression for #3708 — session card title must name an issue in the timeline.

When a session rolls one thread with issue #N and later rates a different
thread with issue #M, the history card for the rolled thread must keep #N,
not borrow #M from the rate event.
"""
from datetime import UTC, datetime

from app.models import Event
from app.services.session_history_projection import (
    project_session_history_events,
    resolve_history_issue_identity,
)


def _evt(
    *,
    event_id: int,
    session_id: int,
    event_type: str,
    selected_thread_id: int | None = None,
    thread_id: int | None = None,
    issue_id: int | None = None,
    issue_number: str | None = None,
) -> Event:
    return Event(
        id=event_id,
        session_id=session_id,
        type=event_type,
        timestamp=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
        selected_thread_id=selected_thread_id,
        thread_id=thread_id,
        issue_id=issue_id,
        issue_number=issue_number,
    )


def test_3708_roll_identity_preserved_over_cross_thread_rate() -> None:
    """Roll Starman #45; rate B.P.R.D. #1 — card must stay #45."""
    events = [
        _evt(event_id=1, session_id=101, event_type="roll", selected_thread_id=1, issue_id=10, issue_number="45"),
        _evt(event_id=2, session_id=101, event_type="rate", thread_id=2, issue_id=20, issue_number="1"),
    ]
    proj = project_session_history_events([101], events)
    # Rolled thread (1) keeps its roll identity; rated thread (2) keeps its rate identity.
    assert resolve_history_issue_identity(proj, 101, 1) == (10, "45")
    assert resolve_history_issue_identity(proj, 101, 2) == (20, "1")


def test_3708_rate_does_not_overwrite_roll_on_same_thread() -> None:
    """If roll then rate both on same thread with different issues, roll wins."""
    events = [
        _evt(event_id=1, session_id=102, event_type="roll", selected_thread_id=5, issue_id=50, issue_number="7"),
        _evt(event_id=2, session_id=102, event_type="rate", thread_id=5, issue_id=51, issue_number="8"),
    ]
    proj = project_session_history_events([102], events)
    assert resolve_history_issue_identity(proj, 102, 5) == (50, "7")
