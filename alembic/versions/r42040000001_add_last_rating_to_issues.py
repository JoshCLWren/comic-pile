"""Add last_rating to issues (#4204).

Revision ID: r42040000001
Revises: c42100000001
Create Date: 2026-10-26 00:00:00.000000

A Thread issue row must be able to show the score the reader gave that exact
issue after a reload. ``threads.last_rating`` holds the most recent score for
the whole series, so it cannot identify a single row's saved rating; the score
is therefore stored on the issue itself.

Existing ratings live in ``events`` (``type = 'rate'`` with ``issue_id`` set),
so the column is backfilled from each issue's most recent rate event before the
row-level label can be read. Issues that were never rated stay NULL.

Undo keeps the original ``rate`` event and adds an ``undo`` event, so a rating
that the reader already reversed must not be restored as the saved score. The
backfill nets undo events against rate events per session the same way
``build_narrative_summary`` does (each undo pops the most recent not-yet-undone
rate) and skips any rate event that was undone.

This revision extends the repository's single head, which is now
``c42100000001`` (tag-name normalization, #4182). It must never point at an
interior revision such as ``c30740000001``: that revision already has a child,
so forking off it would leave two Alembic heads and make ``alembic upgrade
head`` fail on deployment.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r42040000001"
down_revision: str | Sequence[str] | None = "c30740000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _undone_rate_event_ids(bind: sa.engine.Connection) -> set[int]:
    """Return the ids of rate events reversed by an undo event.

    Mirrors ``app.services.summary_service.build_narrative_summary``: events are
    processed per session in ``(timestamp, id)`` order, each ``rate`` is pushed
    onto a stack, and each ``undo`` pops the most recent not-yet-undone rate.
    Rate events with no session cannot be undone and are never included.
    """
    rows = bind.execute(
        sa.text(
            "SELECT id, type, session_id, timestamp "
            "FROM events WHERE type IN ('rate', 'undo') "
            "ORDER BY session_id, timestamp, id"
        )
    ).fetchall()

    by_session: dict[object, list[tuple[int, str, object]]] = defaultdict(list)
    for row in rows:
        by_session[row.session_id].append((row.id, row.type, row.timestamp))

    undone: set[int] = set()
    for _session_id, events in by_session.items():
        if _session_id is None:
            # Undo events always carry a session_id, so a NULL session has no
            # undo stream and none of its rates can be reversed.
            continue
        ordered = sorted(events, key=lambda item: (item[2], item[0]))
        open_rates: list[int] = []
        for event_id, event_type, _timestamp in ordered:
            if event_type == "rate":
                open_rates.append(event_id)
            elif event_type == "undo" and open_rates:
                undone.add(open_rates.pop())
    return undone


def _backfill_last_rating(bind: sa.engine.Connection) -> None:
    """Populate ``issues.last_rating`` from the latest non-undone rate event."""
    undone_ids = _undone_rate_event_ids(bind)

    rate_rows = bind.execute(
        sa.text(
            "SELECT id, issue_id, rating FROM events "
            "WHERE type = 'rate' AND issue_id IS NOT NULL AND rating IS NOT NULL"
        )
    ).fetchall()

    best: dict[int, tuple[int, float]] = {}
    for row in rate_rows:
        if row.id in undone_ids:
            continue
        issue_id = int(row.issue_id)
        if issue_id not in best or int(row.id) > best[issue_id][0]:
            best[issue_id] = (int(row.id), float(row.rating))

    for issue_id, (_event_id, rating) in best.items():
        bind.execute(
            sa.text("UPDATE issues SET last_rating = :rating WHERE id = :id"),
            {"rating": rating, "id": issue_id},
        )


def upgrade() -> None:
    """Add the per-issue saved rating and backfill it from rate events."""
    op.add_column("issues", sa.Column("last_rating", sa.Float(), nullable=True))
    bind = op.get_bind()
    _backfill_last_rating(bind)


def downgrade() -> None:
    """Drop the per-issue saved rating."""
    op.drop_column("issues", "last_rating")
