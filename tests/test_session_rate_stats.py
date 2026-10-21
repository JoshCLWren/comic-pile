"""Unit tests for undo-aware reading totals (#3195, #3708).

The session card and the History card both show how many issues a session read
and the most recent rating. Undo cancels the newest reading, so these totals
come from replaying the ordered rate/undo stream. These tests exercise that
rule without a database so a regression is caught before the API surface.
"""

from app.models import Event
from app.services.session_rate_stats import aggregate_session_rate_stats


def _rate(
    session_id: int,
    *,
    rating: float | None,
    issues_read: int | None,
) -> Event:
    """Build a transient rate event for one session.

    Args:
        session_id: Session the event belongs to.
        rating: Rating recorded by the event, if any.
        issues_read: Issues recorded as read by the event, if any.

    Returns:
        An unsaved rate event.
    """
    return Event(
        type="rate",
        session_id=session_id,
        rating=rating,
        issues_read=issues_read,
    )


def _undo(session_id: int) -> Event:
    """Build a transient undo event for one session.

    Args:
        session_id: Session the event belongs to.

    Returns:
        An unsaved undo event with no die step.
    """
    return Event(type="undo", session_id=session_id)


def test_undo_cancels_only_the_newest_reading() -> None:
    """Undo removes the newest count and rating, keeping the earlier reading."""
    events = [
        _rate(7, rating=4.0, issues_read=2),
        _rate(7, rating=5.0, issues_read=1),
        _undo(7),
    ]

    assert aggregate_session_rate_stats(events, [7]) == {7: (2, 4.0)}


def test_repeated_undos_cancel_in_reverse_order() -> None:
    """Two undos cancel the last two readings, leaving the oldest one."""
    events = [
        _rate(7, rating=3.0, issues_read=1),
        _rate(7, rating=4.0, issues_read=2),
        _rate(7, rating=5.0, issues_read=3),
        _undo(7),
        _undo(7),
    ]

    assert aggregate_session_rate_stats(events, [7]) == {7: (1, 3.0)}


def test_undo_of_every_reading_reports_no_activity() -> None:
    """Canceling the last open reading clears both totals."""
    events = [_rate(7, rating=4.0, issues_read=2), _undo(7)]

    assert aggregate_session_rate_stats(events, [7]) == {7: (0, None)}


def test_undo_without_open_reading_is_not_counted() -> None:
    """An undo with nothing left to cancel leaves the totals untouched."""
    events = [_undo(7), _rate(7, rating=4.5, issues_read=1)]

    assert aggregate_session_rate_stats(events, [7]) == {7: (1, 4.5)}


def test_read_without_rating_keeps_the_last_rating() -> None:
    """A rated read followed by an unrated read keeps the reader's rating."""
    events = [
        _rate(7, rating=4.0, issues_read=1),
        _rate(7, rating=None, issues_read=2),
    ]

    assert aggregate_session_rate_stats(events, [7]) == {7: (3, 4.0)}


def test_sessions_are_aggregated_independently() -> None:
    """An undo in one session never changes another session's totals."""
    events = [
        _rate(7, rating=4.0, issues_read=2),
        _rate(8, rating=3.0, issues_read=1),
        _undo(8),
    ]

    assert aggregate_session_rate_stats(events, [7, 8]) == {7: (2, 4.0), 8: (0, None)}


def test_sessions_without_events_report_zero() -> None:
    """A session with no rate activity reports the empty totals."""
    assert aggregate_session_rate_stats([], [9]) == {9: (0, None)}
