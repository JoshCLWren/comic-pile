"""Tests for bounded session-history event projection."""

from datetime import UTC, datetime

from app.models import Event
from app.services.session_history_projection import project_session_history_events


def _event(
    *,
    event_id: int,
    session_id: int | None,
    event_type: str,
    selected_thread_id: int | None = None,
    die_after: int | None = None,
) -> Event:
    """Build an ordered event fixture without database persistence."""
    return Event(
        id=event_id,
        session_id=session_id,
        type=event_type,
        timestamp=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
        selected_thread_id=selected_thread_id,
        die_after=die_after,
    )


def test_projection_keeps_latest_roll_and_chronological_die_path() -> None:
    events = [
        _event(event_id=1, session_id=10, event_type="roll", selected_thread_id=101),
        _event(event_id=2, session_id=10, event_type="rate", die_after=6),
        _event(event_id=3, session_id=10, event_type="snooze", die_after=8),
        _event(event_id=4, session_id=10, event_type="roll", selected_thread_id=102),
    ]

    projection = project_session_history_events([10], events)

    assert projection.latest_roll_by_session[10].selected_thread_id == 102
    assert projection.die_path_by_session[10] == (6, 8)
    assert projection.latest_die_by_session[10] == 8


def test_projection_uses_event_order_to_break_duplicate_timestamps() -> None:
    events = [
        _event(event_id=20, session_id=10, event_type="undo", die_after=6),
        _event(event_id=21, session_id=10, event_type="rate", die_after=12),
    ]

    projection = project_session_history_events([10], events)

    assert projection.die_path_by_session[10] == (6, 12)
    assert projection.latest_die_by_session[10] == 12


def test_projection_ignores_events_outside_the_bounded_page() -> None:
    events = [
        _event(event_id=1, session_id=10, event_type="rate", die_after=6),
        _event(event_id=2, session_id=11, event_type="rate", die_after=20),
        _event(event_id=3, session_id=None, event_type="rate", die_after=100),
    ]

    projection = project_session_history_events([10], events)

    assert projection.die_path_by_session == {10: (6,)}
    assert projection.latest_die_by_session == {10: 6}
    assert projection.latest_roll_by_session == {}


def test_projection_preserves_empty_sessions_for_constant_time_fallbacks() -> None:
    projection = project_session_history_events([10, 11], [])

    assert projection.die_path_by_session == {10: (), 11: ()}
    assert projection.latest_die_by_session == {}
    assert projection.latest_roll_by_session == {}
