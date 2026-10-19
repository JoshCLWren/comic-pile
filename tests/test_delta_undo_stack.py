"""Tests for stack-safe delta undo behavior and die history."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Snapshot, Thread, User
from app.models import ReadingSession
from app.services.session_response import build_ladder_path
from app.services.snapshot_contract import SNAPSHOT_VERSION, SNAPSHOT_VERSION_KEY
from comic_pile.reading_session import get_current_die


def _thread_state(thread: Thread, *, issues_remaining: int) -> dict:
    """Build the minimal pre-rating thread state needed by delta restoration."""
    return {
        "title": thread.title,
        "format": thread.format,
        "issues_remaining": issues_remaining,
        "last_rating": None,
        "queue_position": thread.queue_position,
        "status": "active",
        "notes": None,
        "is_test": False,
        "is_blocked": False,
        "last_activity_at": None,
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
    session = ReadingSession(
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
        f"/api/v1/undo/{session.id}/undo/{first_snapshot.id}",
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["detail"] == "Only the latest rating can be undone"

    await async_db.refresh(first_thread)
    await async_db.refresh(second_thread)
    assert first_thread.issues_remaining == 4
    assert second_thread.issues_remaining == 4

    second_undo = await auth_client.post(
        f"/api/v1/undo/{session.id}/undo/{second_snapshot.id}",
    )
    assert second_undo.status_code == 200
    assert second_undo.json()["current_die"] == 8
    assert second_undo.json()["ladder_path"] == "6 → 8 → 10 → 8"
    assert second_undo.json()["snapshot_count"] == 1
    assert second_undo.json()["has_restore_point"] is True

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
        f"/api/v1/undo/{session.id}/undo/{first_snapshot.id}",
    )
    assert first_undo.status_code == 200
    assert first_undo.json()["current_die"] == 6
    assert first_undo.json()["ladder_path"] == "6 → 8 → 10 → 8 → 6"
    assert first_undo.json()["snapshot_count"] == 0
    assert first_undo.json()["has_restore_point"] is False

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
        f"/api/v1/undo/{session.id}/undo/{first_snapshot.id}",
    )
    assert repeated_undo.status_code == 404


@pytest.mark.asyncio
async def test_rate_undo_rate_undo_keeps_every_snapshot_count_in_sync(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Keep rating after an undo undoable, with every snapshot count agreeing (#3468).

    The reported sequence is rate -> undo -> rate -> undo. The undo response used
    to subtract the consumed delta a second time, so it reported one fewer
    snapshot than the session list and the History card showed, and the second
    rating then looked like it had no undo point at all.
    """
    thread = Thread(
        title="Re-rate After Undo",
        format="comic",
        issues_remaining=6,
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    roll_response = await auth_client.post("/api/v1/roll/")
    assert roll_response.status_code == 200

    current_response = await auth_client.get("/api/v1/sessions/current/")
    assert current_response.status_code == 200
    session_id = current_response.json()["id"]

    async def snapshot_rows() -> list[dict]:
        """Return the snapshot rows newest-first, as both snapshot views read them."""
        session_rows = await auth_client.get(f"/api/v1/sessions/{session_id}/snapshots")
        assert session_rows.status_code == 200
        undo_rows = await auth_client.get(f"/api/v1/undo/{session_id}/snapshots")
        assert undo_rows.status_code == 200
        # Roll's undo list and the session view are the same rows.
        assert [(row["id"], row["description"]) for row in undo_rows.json()["snapshots"]] == [
            (row["id"], row["description"]) for row in session_rows.json()["snapshots"]
        ]
        return session_rows.json()["snapshots"]

    async def history_card_count() -> int:
        """Return the snapshot count the History card renders for this session."""
        history_response = await auth_client.get("/api/v1/sessions/?page_size=200")
        assert history_response.status_code == 200
        card = next(
            item
            for item in history_response.json()["sessions"]
            if item["id"] == session_id
        )
        return int(card["snapshot_count"])

    async def assert_every_count_agrees() -> int:
        """Assert every reported snapshot count describes the stored rows."""
        rows = await snapshot_rows()
        detail_response = await auth_client.get(f"/api/v1/sessions/{session_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["snapshot_count"] == len(rows)
        assert detail["has_restore_point"] is (len(rows) > 0)
        assert await history_card_count() == len(rows)
        return len(rows)

    first_rate = await auth_client.post(
        "/api/v1/rate/", json={"rating": 5.0, "issues_read": 1}
    )
    assert first_rate.status_code == 200
    rows_after_first_rate = await assert_every_count_agrees()
    first_undo_point = (await snapshot_rows())[0]
    assert first_undo_point["description"] == "After rating"

    first_undo = await auth_client.post(
        f"/api/v1/undo/{session_id}/undo/{first_undo_point['id']}"
    )
    assert first_undo.status_code == 200
    rows_after_first_undo = await assert_every_count_agrees()
    assert rows_after_first_undo == rows_after_first_rate - 1
    assert first_undo.json()["snapshot_count"] == rows_after_first_undo
    assert first_undo.json()["has_restore_point"] is (rows_after_first_undo > 0)

    # The undo restores the rated thread as the pending target, so the reader can
    # rate again and that second rating has its own undo point.
    second_rate = await auth_client.post(
        "/api/v1/rate/", json={"rating": 4.0, "issues_read": 1}
    )
    assert second_rate.status_code == 200
    rows_after_second_rate = await assert_every_count_agrees()
    assert rows_after_second_rate == rows_after_first_rate
    second_undo_point = (await snapshot_rows())[0]
    assert second_undo_point["description"] == "After rating"
    assert second_undo_point["id"] != first_undo_point["id"]

    second_undo = await auth_client.post(
        f"/api/v1/undo/{session_id}/undo/{second_undo_point['id']}"
    )
    assert second_undo.status_code == 200
    rows_after_second_undo = await assert_every_count_agrees()
    assert rows_after_second_undo == rows_after_second_rate - 1
    assert second_undo.json()["snapshot_count"] == rows_after_second_undo
    assert second_undo.json()["has_restore_point"] is (rows_after_second_undo > 0)

    # The second undo restores the state from before that second rating.
    await async_db.refresh(thread)
    assert thread.issues_remaining == 6
    assert thread.last_rating is None


@pytest.mark.asyncio
async def test_session_apis_include_all_die_changing_events(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Keep detail, summary, and direct die calculations aligned after undo."""
    session = ReadingSession(
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

    session_response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert session_response.status_code == 200
    assert session_response.json()["ladder_path"] == "6 → 8 → 10 → 8"
    assert session_response.json()["current_die"] == 8

    details_response = await auth_client.get(f"/api/v1/sessions/{session.id}/details")
    assert details_response.status_code == 200
    assert details_response.json()["ladder_path"] == "6 → 8 → 10 → 8"
    assert details_response.json()["current_die"] == 8

    list_response = await auth_client.get("/api/v1/sessions/?page_size=200")
    assert list_response.status_code == 200
    listed_session = next(
        item for item in list_response.json()["sessions"] if item["id"] == session.id
    )
    assert listed_session["ladder_path"] == "6 → 8 → 10 → 8"
    assert listed_session["current_die"] == 8
