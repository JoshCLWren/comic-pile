"""Ephemeral reading-intent state for active sessions.

Intent state is session-scoped and ephemeral (issue #1728): it lives only on
the :class:`~app.models.session.Session` row, never on Thread or durable
affinity data. Bandwidth state has its own symmetric module
(:mod:`comic_pile.bandwidth`); this module is the small parity surface for
clearing a session's intent lifetime so explicit manual overrides and future
inference prediction never leak across sessions.
"""

from __future__ import annotations

from app.models import Session


def clear_ephemeral_intent(session: Session) -> None:
    """Clear all ephemeral reading-intent state from a session in memory.

    Ending a session terminates its ephemeral intent lifetime, and newly
    started sessions begin without inherited intent (every intent column
    defaults to NULL), so intent never leaks across session boundaries.

    Args:
        session: The session whose intent state should be cleared.
    """
    session.active_intent = None
    session.predicted_intent = None
    session.intent_confidence = None
    session.intent_source = None
    session.intent_version = None
