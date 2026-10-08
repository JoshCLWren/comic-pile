"""Regression tests for issue #3194 rating-undo visibility and History counts.

#3194 reported that the History session card kept counting a rating the reader
had already undone. The cause was in ``GET /v1/sessions/``: the History event
query only selected ``undo``/``restore``/``snooze``/``unsnooze`` rows when
``die_after`` was populated. ``UndoSnapshotService`` writes the undo event with
``die_after`` taken from the snapshot's restored die, which a rating delta
snapshot does not carry, so every rating undo produced an event with a null
``die_after``. Those events were filtered out before the aggregation loop could
pair them with the rating they reversed, leaving the undone issues counted as
read and ``last_rating`` pointing at the undone value.

These tests pin the observable behavior rather than the query text, so the same
bug cannot return behind a different filter.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Thread
from app.models.user import User


async def _seed_session(
    db: AsyncSession,
    user: User,
    events: Sequence[Event],
) -> ReadingSession:
    """Create a reading session and replay ordered event rows for it.

    Args:
        db: SQLAlchemy session for database operations.
        user: Session owner.
        events: Events in chronological order. Their session and timestamp are
            assigned here so each test reads as a plain event log.

    Returns:
        The committed ReadingSession.
    """
    session = ReadingSession(
        start_die=6,
        user_id=user.id,
        started_at=datetime.now(UTC),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    base = datetime.now(UTC)
    for index, event in enumerate(events):
        event.session_id = session.id
        event.timestamp = base + timedelta(seconds=index)
        db.add(event)
    await db.commit()
    await db.refresh(session)
    return session


async def _history_card(auth_client: AsyncClient, session_id: int) -> dict[str, object]:
    """Fetch the History session row that carries the aggregate counts.

    Args:
        auth_client: Authenticated HTTP client.
        session_id: Session whose History row should be read.

    Returns:
        The matching History session payload.
    """
    response = await auth_client.get("/api/v1/sessions/")
    assert response.status_code == 200
    rows: list[dict[str, object]] = response.json()["sessions"]
    return next(row for row in rows if row["id"] == session_id)


@pytest.mark.asyncio
async def test_history_excludes_a_rating_that_was_undone(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """An undone rating must not count toward the session's issues-read total."""
    thread = Thread(
        title="Saga",
        format="comic",
        issues_remaining=9,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    session = await _seed_session(
        async_db,
        default_user,
        [
            Event(
                type="roll",
                die=6,
                result=4,
                selected_thread_id=thread.id,
                selection_method="random",
            ),
            Event(
                type="rate",
                thread_id=thread.id,
                rating=2.0,
                issues_read=1,
                die=6,
                die_after=8,
            ),
            # Exactly what UndoSnapshotService writes for a rating delta
            # snapshot: no die_after, because the snapshot carries no restored
            # die for the ladder.
            Event(type="undo", thread_id=thread.id, die=8, die_after=None),
        ],
    )

    card = await _history_card(auth_client, session.id)
    assert card["issues_read"] == 0
    assert card["last_rating"] is None


@pytest.mark.asyncio
async def test_history_keeps_only_the_ratings_that_survived_an_undo(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A single undo reverses only the most recent rating, not the whole session."""
    thread = Thread(
        title="Saga",
        format="comic",
        issues_remaining=8,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    session = await _seed_session(
        async_db,
        default_user,
        [
            Event(
                type="rate",
                thread_id=thread.id,
                rating=5.0,
                issues_read=1,
                die=6,
                die_after=8,
            ),
            Event(
                type="rate",
                thread_id=thread.id,
                rating=1.0,
                issues_read=1,
                die=8,
                die_after=2,
            ),
            Event(type="undo", thread_id=thread.id, die=2, die_after=None),
        ],
    )

    card = await _history_card(auth_client, session.id)
    assert card["issues_read"] == 1
    assert card["last_rating"] == 5.0


@pytest.mark.asyncio
async def test_history_ladder_path_ignores_undo_events_without_a_die(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Counting undo events must not inject phantom steps into the ladder path.

    The undo event is read for aggregate accounting, but only die-bearing events
    belong on the ladder. Widening the History event query must leave the ladder
    and the reported current die exactly as they were.
    """
    thread = Thread(
        title="Saga",
        format="comic",
        issues_remaining=9,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    session = await _seed_session(
        async_db,
        default_user,
        [
            Event(
                type="roll",
                die=6,
                result=4,
                selected_thread_id=thread.id,
                selection_method="random",
            ),
            Event(
                type="rate",
                thread_id=thread.id,
                rating=4.0,
                issues_read=1,
                die=6,
                die_after=8,
            ),
            Event(type="undo", thread_id=thread.id, die=8, die_after=None),
        ],
    )

    card = await _history_card(auth_client, session.id)
    assert card["ladder_path"] == "d6 → d8"
    assert card["current_die"] == 8