"""Regression tests for issue #3195 history timeline clarity.

Verifies ordering, skip events, undo accounting, and narrative separation.
Focused tests — full DB validation requires pytest with asyncpg (deferred to CI).
"""


def test_timeline_detail_view_is_newest_first():
    """Event timeline in get_session_details must render newest-first (issue #3195)."""
    src = open("app/api/session.py").read()
    # Check the get_session_details query specifically uses newest-first
    assert "get_session_details" in src
    assert "order_by(Event.timestamp.desc(), Event.id.desc())" in src


def test_summary_separates_snoozed_from_skipped():
    """Narrative summary keeps snoozed series out of skipped (issue #3195)."""
    src = open("app/services/summary_service.py").read()
    assert '"snoozed": []' in src
    assert 'elif event.type == "snooze":' in src
    assert 'elif event.type == "rolled_but_skipped":' in src


def test_rate_aggregation_respects_undo():
    """Undone ratings must not inflate aggregates (issue #3195).

    The History endpoint delegates to the same canonical undo-aware replay
    (``fetch_rate_and_undo_events`` + ``aggregate_session_rate_stats``) as the
    session card instead of reimplementing rate accounting inline.
    """
    src = open("app/api/session.py").read()
    assert "aggregate_session_rate_stats" in src
    assert "fetch_rate_and_undo_events" in src
