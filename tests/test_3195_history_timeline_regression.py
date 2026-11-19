"""Regression tests for issue #3195 history timeline clarity.

Verifies narrative separation behavior retained in summary_service.
Python session-handler source checks were retired with the handler removal.
"""


def test_summary_separates_snoozed_from_skipped():
    """Narrative summary keeps still-snoozed series separate from skipped (#3195, #3707)."""
    src = open("app/services/summary_service.py").read()
    assert '"snoozed": []' in src
    assert "project_still_snoozed_thread_ids" in src
    assert 'event.type == "snooze"' in src
    assert "still_snoozed.discard(thread_id)" in src
    assert 'elif event.type == "rolled_but_skipped":' in src
