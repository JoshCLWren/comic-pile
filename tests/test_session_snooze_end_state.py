"""Historical end-of-session snooze projection (#3707).

The History summary's snoozed section is a projection of the snooze state at
the session boundary, not a log of every snooze event. These focused tests
cover replay, toggles, session/reader scoping, start-state evidence, and the
no-mutation guarantee.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Snapshot, Thread, User
from tests.conftest import get_or_create_user_async


def _thread(user_id: int, title: str, position: int) -> Thread:
    """Build an active thread owned by the given reader."""
    return Thread(
        title=title,
        format="Comic",
        issues_remaining=5,
        queue_position=position,
        status="active",
        user_id=user_id,
    )


async def _details(client: AsyncClient, session_id: int) -> dict[str, list[str]]:
    """Fetch the historical narrative summary for one session."""
    response = await client.get(f"/api/v1/sessions/{session_id}/details")
    assert response.status_code == 200
    return response.json()["narrative_summary"]


@pytest.mark.asyncio
async def test_snooze_then_unsnooze_is_not_still_snoozed(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A series snoozed and then unsnoozed in one session is not counted."""
    thread = _thread(default_user.id, "Saga", 1)
    async_db.add(thread)
    await async_db.flush()

    started_at = datetime.now(UTC) - timedelta(minutes=30)
    session = ReadingSession(
        user_id=default_user.id,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=20),
    )
    async_db.add(session)
    await async_db.flush()

    async_db.add_all(
        [
            Event(
                type="snooze",
                session_id=session.id,
                thread_id=thread.id,
                timestamp=started_at + timedelta(minutes=5),
            ),
            Event(
                type="unsnooze",
                session_id=session.id,
                thread_id=thread.id,
                timestamp=started_at + timedelta(minutes=10),
            ),
        ]
    )
    await async_db.commit()

    details = await auth_client.get(f"/api/v1/sessions/{session.id}/details")
    assert details.status_code == 200
    body = details.json()
    assert body["narrative_summary"]["snoozed"] == []
    # The detailed timeline keeps both historical actions (newest first).
    timeline_types = [event["type"] for event in body["events"] if event["type"] in {"snooze", "unsnooze"}]
    assert sorted(timeline_types) == ["snooze", "unsnooze"]


@pytest.mark.asyncio
async def test_multiple_toggles_and_series_keep_only_final_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Repeated toggles across series resolve to the boundary state."""
    first = _thread(default_user.id, "Saga", 1)
    second = _thread(default_user.id, "Monstress", 2)
    async_db.add_all([first, second])
    await async_db.flush()

    started_at = datetime.now(UTC) - timedelta(minutes=40)
    session = ReadingSession(
        user_id=default_user.id,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=30),
    )
    async_db.add(session)
    await async_db.flush()

    async_db.add_all(
        [
            Event(
                type="snooze",
                session_id=session.id,
                thread_id=first.id,
                timestamp=started_at + timedelta(minutes=1),
            ),
            Event(
                type="unsnooze",
                session_id=session.id,
                thread_id=first.id,
                timestamp=started_at + timedelta(minutes=2),
            ),
            Event(
                type="snooze",
                session_id=session.id,
                thread_id=first.id,
                timestamp=started_at + timedelta(minutes=3),
            ),
            Event(
                type="snooze",
                session_id=session.id,
                thread_id=second.id,
                timestamp=started_at + timedelta(minutes=4),
            ),
        ]
    )
    await async_db.commit()

    summary = await _details(auth_client, session.id)
    # Both series end the session snoozed, despite the earlier toggle.
    assert summary["snoozed"] == ["Monstress", "Saga"]


@pytest.mark.asyncio
async def test_session_ending_with_snooze_active_is_counted(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A series still snoozed when the session ends appears in the summary."""
    thread = _thread(default_user.id, "Saga", 1)
    async_db.add(thread)
    await async_db.flush()

    started_at = datetime.now(UTC) - timedelta(minutes=20)
    session = ReadingSession(
        user_id=default_user.id,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=10),
    )
    async_db.add(session)
    await async_db.flush()

    async_db.add(
        Event(
            type="snooze",
            session_id=session.id,
            thread_id=thread.id,
            timestamp=started_at + timedelta(minutes=5),
        )
    )
    await async_db.commit()

    summary = await _details(auth_client, session.id)
    assert summary["snoozed"] == ["Saga"]


@pytest.mark.asyncio
async def test_later_session_unsnooze_does_not_rewrite_history(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A later session's unsnooze leaves the earlier session's result intact."""
    thread = _thread(default_user.id, "Saga", 1)
    async_db.add(thread)
    await async_db.flush()

    started_at = datetime.now(UTC) - timedelta(hours=3)
    first_session = ReadingSession(
        user_id=default_user.id,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=15),
    )
    later_session = ReadingSession(
        user_id=default_user.id,
        started_at=started_at + timedelta(hours=1),
        ended_at=started_at + timedelta(hours=1, minutes=15),
    )
    async_db.add_all([first_session, later_session])
    await async_db.flush()

    async_db.add_all(
        [
            Event(
                type="snooze",
                session_id=first_session.id,
                thread_id=thread.id,
                timestamp=started_at + timedelta(minutes=5),
            ),
            Event(
                type="unsnooze",
                session_id=later_session.id,
                thread_id=thread.id,
                timestamp=started_at + timedelta(hours=1, minutes=5),
            ),
        ]
    )
    await async_db.commit()

    assert (await _details(auth_client, first_session.id))["snoozed"] == ["Saga"]
    assert (await _details(auth_client, later_session.id))["snoozed"] == []


@pytest.mark.asyncio
async def test_persisted_end_state_is_used_when_no_actions_exist(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An ended session that retains its snooze column needs no event replay."""
    thread = _thread(default_user.id, "Saga", 1)
    async_db.add(thread)
    await async_db.flush()

    started_at = datetime.now(UTC) - timedelta(minutes=20)
    session = ReadingSession(
        user_id=default_user.id,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=10),
        snoozed_thread_ids=[thread.id],
    )
    async_db.add(session)
    await async_db.commit()

    assert (await _details(auth_client, session.id))["snoozed"] == ["Saga"]


@pytest.mark.asyncio
async def test_series_already_snoozed_at_session_start_is_counted(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Recorded session-start snoozes seed the historical replay."""
    thread = _thread(default_user.id, "Saga", 1)
    async_db.add(thread)
    await async_db.flush()

    started_at = datetime.now(UTC) - timedelta(minutes=20)
    session = ReadingSession(
        user_id=default_user.id,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=10),
    )
    async_db.add(session)
    await async_db.flush()

    async_db.add(
        Snapshot(
            session_id=session.id,
            event_id=None,
            thread_states={},
            session_state={"snoozed_thread_ids": [thread.id]},
            description="Session start",
            created_at=started_at,
        )
    )
    await async_db.commit()

    assert (await _details(auth_client, session.id))["snoozed"] == ["Saga"]

    # Unsnoozing during the session clears the start-state snooze too.
    async_db.add(
        Event(
            type="unsnooze",
            session_id=session.id,
            thread_id=thread.id,
            timestamp=started_at + timedelta(minutes=5),
        )
    )
    await async_db.commit()

    assert (await _details(auth_client, session.id))["snoozed"] == []


@pytest.mark.asyncio
async def test_session_start_snapshot_records_initial_snooze_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The session-start checkpoint durably records the initial snooze set."""
    from comic_pile.reading_session import create_session_start_snapshot

    thread = _thread(default_user.id, "Saga", 1)
    async_db.add(thread)
    await async_db.flush()

    started_at = datetime.now(UTC) - timedelta(minutes=20)
    session = ReadingSession(
        user_id=default_user.id,
        started_at=started_at,
        snoozed_thread_ids=[thread.id],
    )
    async_db.add(session)
    await async_db.flush()

    await create_session_start_snapshot(async_db, session)

    # Simulate the finish-session path, which clears the live snooze column and
    # leaves the start checkpoint plus the event stream as the only evidence.
    session.ended_at = started_at + timedelta(minutes=10)
    session.snoozed_thread_ids = None
    await async_db.commit()

    assert (await _details(auth_client, session.id))["snoozed"] == ["Saga"]


@pytest.mark.asyncio
async def test_manual_selection_unsnoozes_in_legacy_mode(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Manually selecting a snoozed series clears it and records unsnooze."""
    thread = _thread(default_user.id, "Saga", 1)
    async_db.add(thread)
    await async_db.flush()

    # Create an active session (no ended_at), then finish it after manual selection.
    started_at = datetime.now(UTC) - timedelta(minutes=20)
    session = ReadingSession(
        user_id=default_user.id,
        started_at=started_at,
    )
    async_db.add(session)
    await async_db.flush()

    # Snooze the thread in this active session (via event so replay sees it).
    session.snoozed_thread_ids = [thread.id]
    async_db.add(Event(type="snooze", session_id=session.id, thread_id=thread.id))
    await async_db.flush()

    # Manually select the snoozed thread. This should record an unsnooze event.
    from app.services.thread_service import set_pending_thread

    await set_pending_thread(async_db, default_user.id, thread.id)

    # The manual selection must clear the live snooze column too, so the
    # summary's replay-from-start-state path is what this test exercises.
    await async_db.refresh(session, ["snoozed_thread_ids"])
    assert session.snoozed_thread_ids == []

    # Finish the session.
    session.ended_at = started_at + timedelta(minutes=10)
    await async_db.flush()

    summary = await _details(auth_client, session.id)
    assert summary["snoozed"] == []
    # The unsnooze is recorded for durable history.
    result = await async_db.execute(
        select(Event).where(
            Event.session_id == session.id, Event.type.in_(["snooze", "unsnooze"])
        )
    )
    events = result.scalars().all()
    types = sorted(e.type for e in events)
    assert types == ["snooze", "unsnooze"]


@pytest.mark.asyncio
async def test_other_readers_snooze_state_is_not_exposed(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A malformed cross-reader reference cannot leak another reader's series."""
    other_user = await get_or_create_user_async(async_db, username="other_snooze_reader")
    foreign_thread = _thread(other_user.id, "Foreign Series", 1)
    async_db.add(foreign_thread)
    await async_db.flush()

    started_at = datetime.now(UTC) - timedelta(minutes=20)
    session = ReadingSession(
        user_id=default_user.id,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=10),
    )
    async_db.add(session)
    await async_db.flush()

    async_db.add(
        Event(
            type="snooze",
            session_id=session.id,
            thread_id=foreign_thread.id,
            timestamp=started_at + timedelta(minutes=5),
        )
    )
    await async_db.commit()

    summary = await _details(auth_client, session.id)
    assert summary["snoozed"] == []


@pytest.mark.asyncio
async def test_viewing_history_does_not_mutate_events_or_session_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Reading a historical summary is a pure projection over stored history."""
    thread = _thread(default_user.id, "Saga", 1)
    async_db.add(thread)
    await async_db.flush()

    started_at = datetime.now(UTC) - timedelta(minutes=20)
    session = ReadingSession(
        user_id=default_user.id,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=10),
    )
    async_db.add(session)
    await async_db.flush()

    async_db.add_all(
        [
            Event(
                type="snooze",
                session_id=session.id,
                thread_id=thread.id,
                timestamp=started_at + timedelta(minutes=2),
            ),
            Event(
                type="unsnooze",
                session_id=session.id,
                thread_id=thread.id,
                timestamp=started_at + timedelta(minutes=3),
            ),
        ]
    )
    await async_db.commit()

    event_count = await async_db.scalar(
        select(func.count()).select_from(Event).where(Event.session_id == session.id)
    )
    ended_at_before = session.ended_at

    await auth_client.get(f"/api/v1/sessions/{session.id}/details")

    await async_db.refresh(session)
    event_count_after = await async_db.scalar(
        select(func.count()).select_from(Event).where(Event.session_id == session.id)
    )
    assert event_count_after == event_count
    assert session.ended_at == ended_at_before
    assert session.snoozed_thread_ids is None
