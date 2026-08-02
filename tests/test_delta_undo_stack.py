"""Tests for stack-safe delta undo behavior and die history."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import build_ladder_path
from app.models import Event, Snapshot, Thread, User
from app.models import Session as SessionModel
from app.services.snapshot_contract import SNAPSHOT_VERSION, SNAPSHOT_VERSION_KEY
from comic_pile.session import get_current_die


def _thread_state(thread: Thread, *, issues_remaining: int) -> dict:
    """Build the minimal pre-rating thread state needed by delta restoration."""
    return {
        "title": thread.title,
        "format": thread.format,
        "issues_remaining": issues_remaining,
        "last_rating": None,
        "queue_position": thread.queue_position,
        "status": "active",
        "review_url": None,
        "notes": None,
        "is_test": False,
        "is_blocked": False,
        "last_activity_at": None,
        "last_review_at": None,
    }


def _session_state(current_die: int) -> dict:
    """Build session state captured immediately before a rating."""
    return {
        "start_die": 6,
        "manual_die": None,
        "current_die": current_die,
        "pending_thread_id": None,
        "pending_thread_updated_at": None,
        "ended_at": None,
        "snoozed_thread_ids": [],
    }


@pytest.mark.asyncio
async def test_delta_undo_is_lifo_and_consumes_snapshots(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Reject stale delta targets and allow repeated undo only in reverse order."""
    now = datetime.now(UTC)
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=now,
    )
    first_thread = Thread(
        title="First Rating",
        format="comic",
        issues_remaining=4,
        last_rating=5.0,
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    second_thread = Thread(
        title="Second Rating",
        format="comic",
        issues_remaining=4,
        last_rating=5.0,
        queue_position=2,
        status="active",
        user_id=default_user.id,
    )
    async_db.add_all([session, first_thread, second_thread])
    await async_db.commit()
    await async_db.refresh(session)
    await async_db.refresh(first_thread)
    await async_db.refresh(second_thread)

    first_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=first_thread.id,
        rating=5.0,
        issues_read=1,
        die=6,
        die_after=8,
    )
    second_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=second_thread.id,
        rating=5.0,
        issues_read=1,
        die=8,
        die_after=10,
    )
    async_db.add_all([first_event, second_event])
    await async_db.commit()
    await async_db.refresh(first_event)
    await async_db.refresh(second_event)

    first_snapshot = Snapshot(
        session_id=session.id,
        event_id=first_event.id,
        thread_states={
            SNAPSHOT_VERSION_KEY: SNAPSHOT_VERSION,
            str(first_thread.id): _thread_state(first_thread, issues_remaining=5),
        },
        session_state=_session_state(6),
        created_at=now,
        description="Before first rating",
    )
    second_snapshot = Snapshot(
        session_id=session.id,
        event_id=second_event.id,
        thread_states={
            SNAPSHOT_VERSION_KEY: SNAPSHOT_VERSION,
            str(second_thread.id): _thread_state(second_thread, issues_remaining=5),
        },
        session_state=_session_state(8),
        created_at=now + timedelta(seconds=1),
        description="Before second rating",
    )
    async_db.add_all([first_snapshot, second_snapshot])
    await async_db.commit()
    await async_db.refresh(first_snapshot)
    await async_db.refresh(second_snapshot)

    stale_response = await auth_client.post(
        f"/api/undo/{session.id}/undo/{first_snapshot.id}",
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["detail"] == "Only the latest rating can be undone"

    await async_db.refresh(first_thread)
    await async_db.refresh(second_thread)
    assert first_thread.issues_remaining == 4
    assert second_thread.issues_remaining == 4

    second_undo = await auth_client.post(
        f"/api/undo/{session.id}/undo/{second_snapshot.id}",
    )
    assert second_undo.status_code == 200
    assert second_undo.json()["current_die"] == 8
    assert second_undo.json()["ladder_path"] == "6 → 8 → 10 → 8"

    await async_db.refresh(second_thread)
    assert second_thread.issues_remaining == 5
    assert second_thread.last_rating is None

    remaining_snapshot_ids = (
        await async_db.execute(
            select(Snapshot.id)
            .where(Snapshot.session_id == session.id)
            .order_by(Snapshot.id)
        )
    ).scalars().all()
    assert remaining_snapshot_ids == [first_snapshot.id]

    first_undo = await auth_client.post(
        f"/api/undo/{session.id}/undo/{first_snapshot.id}",
    )
    assert first_undo.status_code == 200
    assert first_undo.json()["current_die"] == 6
    assert first_undo.json()["ladder_path"] == "6 → 8 → 10 → 8 → 6"

    await async_db.refresh(first_thread)
    assert first_thread.issues_remaining == 5
    assert first_thread.last_rating is None

    remaining_snapshot_ids = (
        await async_db.execute(
            select(Snapshot.id).where(Snapshot.session_id == session.id)
        )
    ).scalars().all()
    assert remaining_snapshot_ids == []

    repeated_undo = await auth_client.post(
        f"/api/undo/{session.id}/undo/{first_snapshot.id}",
    )
    assert repeated_undo.status_code == 404


@pytest.mark.asyncio
async def test_session_apis_include_all_die_changing_events(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Keep detail, summary, and direct die calculations aligned after undo."""
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    async_db.add_all(
        [
            Event(type="rate", session_id=session.id, die=6, die_after=8, rating=5.0),
            Event(type="snooze", session_id=session.id, die=8, die_after=10),
            Event(type="undo", session_id=session.id, die=10, die_after=8),
        ]
    )
    await async_db.commit()

    assert await build_ladder_path(session.id, async_db) == "6 → 8 → 10 → 8"
    assert await get_current_die(session.id, async_db) == 8

    session_response = await auth_client.get(f"/api/sessions/{session.id}")
    assert session_response.status_code == 200
    assert session_response.json()["ladder_path"] == "6 → 8 → 10 → 8"
    assert session_response.json()["current_die"] == 8

    details_response = await auth_client.get(f"/api/sessions/{session.id}/details")
    assert details_response.status_code == 200
    assert details_response.json()["ladder_path"] == "6 → 8 → 10 → 8"
    assert details_response.json()["current_die"] == 8

    list_response = await auth_client.get("/api/sessions/?page_size=200")
    assert list_response.status_code == 200
    listed_session = next(
        item for item in list_response.json()["sessions"] if item["id"] == session.id
    )
    assert listed_session["ladder_path"] == "6 → 8 → 10 → 8"
    assert listed_session["current_die"] == 8
