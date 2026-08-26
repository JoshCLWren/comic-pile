"""Tests for read-only roll-to-rating decision latency derivation."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread, User
from app.models import Session as SessionModel
from app.services.decision_latency import (
    derive_decision_latencies,
    derive_legacy_order_fallback_latencies,
    derive_roll_rate_latencies,
    load_decision_latency_events,
)

_BASE = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _at(offset_seconds: int) -> datetime:
    """Return a fixed timezone-aware timestamp offset from the shared base."""
    return _BASE + timedelta(seconds=offset_seconds)


def _event(
    event_id: int,
    event_type: str,
    timestamp: datetime,
    *,
    session_id: int | None = 10,
    selected_thread_id: int | None = None,
    thread_id: int | None = None,
    issue_id: int | None = None,
    issue_number: str | None = None,
    source_roll_event_id: int | None = None,
) -> Event:
    """Build an event fixture without database persistence."""
    return Event(
        id=event_id,
        session_id=session_id,
        type=event_type,
        timestamp=timestamp,
        selected_thread_id=selected_thread_id,
        thread_id=thread_id,
        issue_id=issue_id,
        issue_number=issue_number,
        source_roll_event_id=source_roll_event_id,
    )


def test_linked_pair_produces_deterministic_elapsed_durations() -> None:
    """A linked roll/rate pair yields exact seconds and minutes, repeatably."""
    events = [
        _event(1, "roll", _at(0), selected_thread_id=101),
        _event(2, "rate", _at(90), thread_id=101, issue_number="7", source_roll_event_id=1),
    ]

    first = derive_roll_rate_latencies(events)
    second = derive_roll_rate_latencies(list(reversed(events)))

    assert len(first) == 1
    latency = first[0]
    assert latency.roll_event_id == 1
    assert latency.rate_event_id == 2
    assert latency.thread_id == 101
    assert latency.issue_number == "7"
    assert latency.elapsed_seconds == 90.0
    assert latency.elapsed_minutes == 1.5
    assert first == second


def test_multiple_reads_remain_paired_to_their_correct_rolls() -> None:
    """Two reads in one session each stay paired to their own originating roll."""
    events = [
        _event(1, "roll", _at(0), selected_thread_id=101),
        _event(2, "rate", _at(60), thread_id=101, source_roll_event_id=1),
        _event(3, "roll", _at(120), selected_thread_id=102),
        _event(4, "rate", _at(300), thread_id=102, source_roll_event_id=3),
    ]

    latencies = derive_roll_rate_latencies(events)

    assert [(item.roll_event_id, item.rate_event_id) for item in latencies] == [(1, 2), (3, 4)]
    assert [item.elapsed_seconds for item in latencies] == [60.0, 180.0]
    assert [item.thread_id for item in latencies] == [101, 102]


def test_snoozes_and_unrelated_events_do_not_contaminate_durations() -> None:
    """Snoozes, undoes, and skipped outcomes never alter or add latencies."""
    events = [
        _event(1, "roll", _at(0), selected_thread_id=101),
        _event(2, "snooze", _at(30)),
        _event(3, "unsnooze", _at(45)),
        _event(4, "rolled_but_skipped", _at(50), thread_id=102),
        _event(5, "undo", _at(55)),
        _event(6, "rate", _at(120), thread_id=101, source_roll_event_id=1),
        _event(7, "roll", _at(200), selected_thread_id=103),
    ]

    latencies = derive_roll_rate_latencies(events)

    assert len(latencies) == 1
    assert latencies[0].roll_event_id == 1
    assert latencies[0].rate_event_id == 6
    assert latencies[0].elapsed_seconds == 120.0


def test_legacy_unlinked_outcomes_are_tolerated_without_fabricated_links() -> None:
    """Rate events without an explicit link are skipped, not guessed."""
    events = [
        _event(1, "roll", _at(0), selected_thread_id=101),
        _event(2, "rate", _at(60), thread_id=101),
        _event(3, "rate", _at(90), thread_id=102),
        _event(4, "rate", _at(120), thread_id=103, source_roll_event_id=1),
    ]

    latencies = derive_roll_rate_latencies(events)

    assert [item.rate_event_id for item in latencies] == [4]
    assert latencies[0].elapsed_seconds == 120.0


def test_dangling_link_is_skipped_instead_of_fabricated() -> None:
    """A link whose roll is absent from the dataset produces no observation."""
    events = [
        _event(1, "rate", _at(60), thread_id=101, source_roll_event_id=999),
    ]

    assert derive_roll_rate_latencies(events) == []


def test_legacy_fallback_stays_separate_from_the_trusted_dataset() -> None:
    """The ordering fallback covers only unlinked rates and never mixes in."""
    events = [
        _event(1, "roll", _at(0), selected_thread_id=101),
        _event(2, "rate", _at(60), thread_id=101),
        _event(3, "snooze", _at(70)),
        _event(4, "roll", _at(80), selected_thread_id=102),
        _event(5, "rate", _at(140), thread_id=102, source_roll_event_id=4),
    ]

    trusted = derive_roll_rate_latencies(events)
    fallback = derive_legacy_order_fallback_latencies(events)

    assert [(item.roll_event_id, item.rate_event_id) for item in trusted] == [(4, 5)]
    assert [(item.roll_event_id, item.rate_event_id) for item in fallback] == [(1, 2)]
    combined_ids = {item.rate_event_id for item in (*trusted, *fallback)}
    assert len(combined_ids) == len(trusted) + len(fallback)


def test_legacy_fallback_never_crosses_session_boundaries() -> None:
    """Fallback pairing stays within one session and skips rolls without links."""
    events = [
        _event(1, "roll", _at(0), session_id=10, selected_thread_id=101),
        _event(2, "roll", _at(10), session_id=11, selected_thread_id=102),
        _event(3, "rate", _at(70), session_id=11, thread_id=102),
        _event(4, "rate", _at(80), session_id=None, thread_id=103),
    ]

    fallback = derive_legacy_order_fallback_latencies(events)

    assert [(item.session_id, item.roll_event_id, item.rate_event_id) for item in fallback] == [
        (11, 2, 3)
    ]


@pytest.mark.asyncio
async def test_database_loader_and_derivation_read_linked_history(
    async_db: AsyncSession, default_user: User
) -> None:
    """Persisted linked history loads read-only and derives paired latencies."""
    thread_a = Thread(
        title="Latency A",
        format="comic",
        issues_remaining=5,
        queue_position=1,
        user_id=default_user.id,
    )
    thread_b = Thread(
        title="Latency B",
        format="comic",
        issues_remaining=5,
        queue_position=2,
        user_id=default_user.id,
    )
    async_db.add_all([thread_a, thread_b])
    await async_db.commit()

    reading_session = SessionModel(
        start_die=20, user_id=default_user.id, started_at=datetime.now(UTC)
    )
    async_db.add(reading_session)
    await async_db.commit()
    await async_db.refresh(reading_session)

    first_roll = Event(
        type="roll",
        session_id=reading_session.id,
        selected_thread_id=thread_a.id,
        die=20,
        result=4,
        selection_method="random",
        timestamp=_at(0),
    )
    snooze = Event(
        type="snooze",
        session_id=reading_session.id,
        thread_id=thread_b.id,
        die=18,
        die_after=20,
        timestamp=_at(15),
    )
    second_roll = Event(
        type="roll",
        session_id=reading_session.id,
        selected_thread_id=thread_b.id,
        die=20,
        result=9,
        selection_method="random",
        timestamp=_at(30),
    )
    async_db.add_all([first_roll, snooze, second_roll])
    await async_db.commit()
    for event in (first_roll, second_roll):
        await async_db.refresh(event)

    first_rate = Event(
        type="rate",
        session_id=reading_session.id,
        thread_id=thread_a.id,
        rating=4.0,
        issues_read=1,
        die=20,
        die_after=12,
        timestamp=_at(75),
        source_roll_event_id=first_roll.id,
    )
    second_rate = Event(
        type="rate",
        session_id=reading_session.id,
        thread_id=thread_b.id,
        rating=5.0,
        issues_read=1,
        die=20,
        die_after=6,
        timestamp=_at(210),
        source_roll_event_id=second_roll.id,
    )
    legacy_rate = Event(
        type="rate",
        session_id=reading_session.id,
        thread_id=thread_a.id,
        rating=3.0,
        issues_read=1,
        die=6,
        die_after=8,
        timestamp=_at(240),
    )
    async_db.add_all([first_rate, second_rate, legacy_rate])
    await async_db.commit()

    loaded = await load_decision_latency_events(async_db)
    assert {event.type for event in loaded} == {"roll", "rate"}

    latencies = await derive_decision_latencies(async_db, session_ids=[reading_session.id])

    assert [(item.roll_event_id, item.rate_event_id) for item in latencies] == [
        (first_roll.id, first_rate.id),
        (second_roll.id, second_rate.id),
    ]
    assert [item.elapsed_seconds for item in latencies] == [75.0, 180.0]
    assert [item.thread_id for item in latencies] == [thread_a.id, thread_b.id]
