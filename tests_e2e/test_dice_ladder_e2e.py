"""E2E integration tests for dice ladder behavior through API."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dice_ladder_rating_goes_down(auth_api_client: AsyncClient, db: Session) -> None:
    """Rating 4+ causes session die to go DOWN (d10 → d8)."""
    from app.models import User

    user = db.execute(select(User).where(User.username == "test_user@example.com")).scalar_one()

    # Create thread
    thread = Thread(
        title="Green Lantern",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    # Create session starting at d10
    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    # Roll
    roll_response = await auth_api_client.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()

    # Verify we're at d10
    assert roll_data["die_size"] == 10

    # Rate 4.0 (should step die DOWN to d8)
    rate_response = await auth_api_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert rate_response.status_code == 200

    # Check rate event was created with die_after = 8
    rate_events = (
        db.execute(
            select(Event)
            .where(Event.session_id == session.id)
            .where(Event.type == "rate")
            .order_by(Event.timestamp.desc())
        )
        .scalars()
        .all()
    )
    assert len(rate_events) == 1
    assert rate_events[0].die_after == 8


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dice_ladder_rating_goes_up(auth_api_client: AsyncClient, db: Session) -> None:
    """Rating below 4 causes session die to go UP (d10 → d12)."""
    from app.models import User

    user = db.execute(select(User).where(User.username == "test_user@example.com")).scalar_one()

    thread = Thread(
        title="Shazam",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    # Roll
    roll_response = await auth_api_client.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()

    # Verify we're at d10
    assert roll_data["die_size"] == 10

    # Rate 3.0 (should step die UP to d12)
    rate_response = await auth_api_client.post("/api/rate/", json={"rating": 3.0, "issues_read": 1})
    assert rate_response.status_code == 200

    # Check rate event was created with die_after = 12
    rate_events = (
        db.execute(
            select(Event)
            .where(Event.session_id == session.id)
            .where(Event.type == "rate")
            .order_by(Event.timestamp.desc())
        )
        .scalars()
        .all()
    )
    assert len(rate_events) == 1
    assert rate_events[0].die_after == 12


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dice_ladder_snooze_goes_up(auth_api_client: AsyncClient, db: Session) -> None:
    """Snoozing causes session die to go UP (d6 → d8)."""
    from app.models import User

    user = db.execute(select(User).where(User.username == "test_user@example.com")).scalar_one()

    thread = Thread(
        title="Batman Beyond",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    # Roll
    roll_response = await auth_api_client.post("/api/roll/")
    assert roll_response.status_code == 200

    # Verify we're at d6
    roll_data = roll_response.json()
    assert roll_data["die_size"] == 6

    # Snooze (should step die UP to d8)
    snooze_response = await auth_api_client.post("/api/snooze/")
    assert snooze_response.status_code == 200
    snooze_data = snooze_response.json()

    # Verify die stepped up to d8
    assert snooze_data["manual_die"] == 8

    # Check snooze event was created with die_after = 8
    snooze_events = (
        db.execute(
            select(Event)
            .where(Event.session_id == session.id)
            .where(Event.type == "snooze")
            .order_by(Event.timestamp.desc())
        )
        .scalars()
        .all()
    )
    assert len(snooze_events) == 1
    assert snooze_events[0].die_after == 8


@pytest.mark.asyncio
@pytest.mark.integration
async def test_finish_session_clears_snoozed(auth_api_client: AsyncClient, db: Session) -> None:
    """Verify that finishing a session clears snoozed_thread_ids."""
    from app.models import User

    user = db.execute(select(User).where(User.username == "test_user@example.com")).scalar_one()

    # Create thread1 with issues_remaining=1 so rolling twice completes thread2 first
    thread1 = Thread(
        title="Superman",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    thread2 = Thread(
        title="Wonder Woman",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    db.add(thread1)
    db.add(thread2)
    db.commit()
    db.refresh(thread1)
    db.refresh(thread2)

    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    # Roll and snooze the rolled thread (whichever thread gets selected)
    await auth_api_client.post("/api/roll/")
    snooze_response = await auth_api_client.post("/api/snooze/")
    assert snooze_response.status_code == 200
    snooze_data = snooze_response.json()
    # Verify something was snoozed
    assert len(snooze_data["snoozed_thread_ids"]) == 1

    # Roll again - this should get thread2
    await auth_api_client.post("/api/roll/")

    # Read all issues to complete thread2 so finish_session will trigger
    db.refresh(thread2)
    rate_response = await auth_api_client.post(
        "/api/rate/",
        json={"rating": 4.0, "issues_read": thread2.issues_remaining, "finish_session": True},
    )
    assert rate_response.status_code == 200

    # Verify session ended
    db.refresh(session)
    assert session.ended_at is not None

    # Verify snoozed_thread_ids was cleared
    snoozed_count = len(session.snoozed_thread_ids) if session.snoozed_thread_ids else 0
    assert snoozed_count == 0
