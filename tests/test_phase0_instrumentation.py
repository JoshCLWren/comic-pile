"""Tests for Phase 0 instrumentation: source-roll linkage and issue snapshots.

Covers:
- #1686: source_roll_event_id on rate/snooze events
- #1689: issue_id/issue_number populated on roll events
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_roll_populates_issue_id_and_number(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Roll event persists issue_id and issue_number for issue-tracked threads."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=8, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Issue-Tracked Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=10,
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    issue = Issue(
        thread_id=thread.id,
        issue_number="3",
        status="unread",
        position=3,
    )
    async_db.add(issue)
    await async_db.commit()
    await async_db.refresh(issue)

    thread.next_unread_issue_id = issue.id
    await async_db.commit()

    # Ensure no pending roll blocks the new roll (409 guard in app/api/roll.py:66).
    assert session.pending_thread_id is None

    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200

    data = response.json()
    assert data["issue_id"] == issue.id
    assert data["issue_number"] == "3"

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "roll")
        .order_by(Event.timestamp.desc())
    )
    roll_event = result.scalars().first()
    assert roll_event is not None
    assert roll_event.issue_id == issue.id
    assert roll_event.issue_number == "3"


@pytest.mark.asyncio
async def test_roll_override_populates_issue_id_and_number(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Override roll event persists issue_id and issue_number."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=8, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Override Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=10,
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    issue = Issue(
        thread_id=thread.id,
        issue_number="2",
        status="unread",
        position=2,
    )
    async_db.add(issue)
    await async_db.commit()
    await async_db.refresh(issue)

    thread.next_unread_issue_id = issue.id
    await async_db.commit()

    response = await auth_client.post(
        "/api/roll/override", json={"thread_id": thread.id}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["issue_id"] == issue.id
    assert data["issue_number"] == "2"

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "roll")
        .order_by(Event.timestamp.desc())
    )
    roll_event = result.scalars().first()
    assert roll_event is not None
    assert roll_event.issue_id == issue.id
    assert roll_event.issue_number == "2"


@pytest.mark.asyncio
async def test_roll_nullable_issue_fields_for_non_issue_tracked(
    auth_client: AsyncClient,
    sample_data: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Roll event has NULL issue_id/issue_number for non-issue-tracked threads."""
    _ = sample_data
    monkeypatch.setattr("app.momentum.random.randint", lambda _start, _end: 0)
    monkeypatch.setattr("app.momentum.random.uniform", lambda _a, _b: 0.0)

    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200

    data = response.json()
    assert data["issue_id"] is None
    assert data["issue_number"] is None


@pytest.mark.asyncio
async def test_rate_links_to_source_roll_event(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Rate event links to the originating roll event via source_roll_event_id."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Rate Link Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    roll_event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
    )
    async_db.add(roll_event)
    await async_db.commit()
    await async_db.refresh(roll_event)

    session.pending_thread_id = thread.id
    await async_db.commit()

    response = await auth_client.post(
        "/api/rate/", json={"rating": 4.0}
    )
    assert response.status_code == 200

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "rate")
        .order_by(Event.timestamp.desc())
    )
    rate_event = result.scalars().first()
    assert rate_event is not None
    assert rate_event.source_roll_event_id == roll_event.id


@pytest.mark.asyncio
async def test_snooze_links_to_source_roll_event(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Snooze event links to the originating roll event via source_roll_event_id."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Snooze Link Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    roll_event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
    )
    async_db.add(roll_event)
    await async_db.commit()
    await async_db.refresh(roll_event)

    session.pending_thread_id = thread.id
    await async_db.commit()

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "snooze")
        .order_by(Event.timestamp.desc())
    )
    snooze_event = result.scalars().first()
    assert snooze_event is not None
    assert snooze_event.source_roll_event_id == roll_event.id


@pytest.mark.asyncio
async def test_rate_links_to_correct_roll_in_multi_roll_session(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Rate links to the correct roll when multiple rolls exist in one session."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread_a = Thread(
        title="Thread A",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    thread_b = Thread(
        title="Thread B",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread_a)
    async_db.add(thread_b)
    await async_db.commit()
    await async_db.refresh(thread_a)
    await async_db.refresh(thread_b)

    roll_a = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread_a.id,
        selection_method="random",
        session_id=session.id,
    )
    async_db.add(roll_a)
    await async_db.commit()
    await async_db.refresh(roll_a)

    session.pending_thread_id = thread_a.id
    await async_db.commit()

    response = await auth_client.post(
        "/api/rate/", json={"rating": 4.0}
    )
    assert response.status_code == 200

    roll_b = Event(
        type="roll",
        die=8,
        result=1,
        selected_thread_id=thread_b.id,
        selection_method="random",
        session_id=session.id,
    )
    async_db.add(roll_b)
    await async_db.commit()
    await async_db.refresh(roll_b)

    session.pending_thread_id = thread_b.id
    await async_db.commit()

    response = await auth_client.post(
        "/api/rate/", json={"rating": 3.0}
    )
    assert response.status_code == 200

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "rate")
        .order_by(Event.timestamp.desc())
    )
    rate_events = result.scalars().all()
    assert len(rate_events) >= 2

    latest_rate = rate_events[0]
    assert latest_rate.source_roll_event_id == roll_b.id


@pytest.mark.asyncio
async def test_unsnooze_does_not_set_source_roll_event_id(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Unsnooze event does not set source_roll_event_id."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Unsnooze Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    roll_event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
    )
    async_db.add(roll_event)
    session.pending_thread_id = thread.id
    await async_db.commit()

    await auth_client.post("/api/snooze/")

    response = await auth_client.post(f"/api/snooze/{thread.id}/unsnooze")
    assert response.status_code == 200

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "unsnooze")
        .order_by(Event.timestamp.desc())
    )
    unsnooze_event = result.scalars().first()
    assert unsnooze_event is not None
    assert unsnooze_event.source_roll_event_id is None


@pytest.mark.asyncio
async def test_existing_events_with_null_source_roll_load_normally(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Historical events with NULL source_roll_event_id continue to work."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Legacy Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    legacy_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.0,
        die=10,
        die_after=8,
    )
    async_db.add(legacy_event)
    await async_db.commit()

    result = await async_db.execute(
        select(Event).where(Event.id == legacy_event.id)
    )
    loaded = result.scalar_one()
    assert loaded.source_roll_event_id is None
