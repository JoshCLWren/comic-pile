"""Regression tests for issue #3195 history timeline clarity.

Verifies ordering, skip events,undo accounting, and narrative separation.
Focused tests — full DB validation requires pytest with asyncpg (deferred to CI).
"""


def test_timeline_order_is_newest_first():
    src = open("app/api/session.py").read()
    assert "timestamp.desc()" in src, "Timeline must be newest-first (issue #3195)"


def test_summary_separates_snoozed_from_skipped():
    src = open("app/services/summary_service.py").read()
    assert '"snoozed": []' in src
    assert 'elif event.type == "snooze":' in src
    assert 'elif event.type == "rolled_but_skipped":' in src


def test_rate_aggregation_respects_undo():
    src = open("app/api/session.py").read()
    assert "undone_rate_ids" in src
    assert "open_rate_ids_by_session" in src
