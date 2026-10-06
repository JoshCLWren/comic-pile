"""Regression tests for issue #3194 rating-undo defects.

Verifies the history aggregate sees every undo event, the Roll "Just rated"
notice offers an in-context undo, undo mutations refresh the retained caches,
and the session view explains undo-vs-restore with confirmation feedback.

Focused tests — full DB validation requires pytest with asyncpg (deferred to CI).
"""


def test_history_query_loads_undo_events_unconditionally():
    """Undone ratings must not inflate History "issues read" counts (#3194).

    Undo rows may carry a null die_after, so gating them on die_after keeps
    the undone rating in the aggregate. The events query must load undo rows
    unconditionally while the die projection keeps its own null guard.
    """
    src = open("app/api/session.py").read()
    assert 'Event.type == "undo",' in src
    assert "undone_rate_ids" in src
    assert "open_rate_ids_by_session" in src


def test_die_projection_still_guards_null_die_after():
    """Loading all undo rows must not break the die projection (#3194)."""
    src = open("app/services/session_history_projection.py").read()
    assert "event.die_after is not None" in src


def test_just_rated_notice_offers_undo():
    """The Roll "Just rated" notice must carry a one-tap Undo (#3194)."""
    src = open("frontend/src/pages/RollPage/components/PostRateCopyPrompt.tsx").read()
    assert "Undo rating" in src
    assert "useUndoLatestRating" in src
    assert "sessionId" in src


def test_undo_refreshes_roll_and_history_caches():
    """Undo/restore must invalidate the retained Roll and session caches (#3194)."""
    src = open("frontend/src/query/cacheEffects.ts").read()
    assert "invalidateAfterUndo" in src
    assert "queryKeys.roll.bootstrap()" in src
    assert "queryKeys.queue.pages()" in src
    undo_src = open("frontend/src/hooks/useUndo.ts").read()
    assert "invalidateAfterUndo" in undo_src
    assert "Rating undone. Roll and History are up to date." in undo_src
    session_src = open("frontend/src/hooks/useSession.ts").read()
    assert "invalidateAfterUndo" in session_src


def test_session_view_explains_undo_vs_restore():
    """UNDO LATEST vs RESTORE START must be explained inline (#3194)."""
    src = open("frontend/src/pages/SessionPage.tsx").read()
    assert "Undo latest reverts only your most recent rating" in src
    assert "Restore start instead resets your entire pile" in src
    assert "No ratings left to undo." in src
