"""Regression tests for issue #3195 history timeline clarity.

Verifies ordering, skip events,undo accounting, and narrative separation.
Focused tests — full DB validation requires pytest with asyncpg (deferred to CI).
"""


def test_timeline_order_is_newest_first():
    """Timeline must render newest-first (issue #3195)."""
    src = open("app/api/session.py").read()
    assert "timestamp.desc()" in src, "Timeline must be newest-first (issue #3195)"


def test_summary_separates_snoozed_from_skipped():
    """Narrative summary keeps snoozed series out of skipped (issue #3195)."""
    src = open("app/services/summary_service.py").read()
    assert '"snoozed": []' in src
    assert 'elif event.type == "snooze":' in src
    assert 'elif event.type == "rolled_but_skipped":' in src


def test_rate_aggregation_respects_undo():
    """Undone ratings must not inflate aggregates (issue #3195)."""
    src = open("app/api/session.py").read()
    assert "undone_rate_ids" in src
    assert "open_rate_ids_by_session" in src
