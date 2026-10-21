"""End-to-end roll/rate consistency tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread, User
from httpx import AsyncClient
from comic_pile.dice_ladder import step_down


@pytest.mark.asyncio
async def test_roll_rate_history_consistency(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Verify roll and rate operations maintain consistent session state across history."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title="Green Lantern",
            format="Comic",
            issues_remaining=5,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Shazam",
            format="Comic",
            issues_remaining=4,
            queue_position=2,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Batman Beyond",
            format="Comic",
            issues_remaining=3,
            queue_position=3,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
    ]

    for thread in threads:
        async_db.add(thread)
    await async_db.commit()

    roll_response = await auth_client.post("/api/v1/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()

    session_after_roll = await auth_client.get("/api/v1/sessions/current/")
    assert session_after_roll.status_code == 200
    session_data = session_after_roll.json()

    active_thread = session_data.get("active_thread")
    assert active_thread is not None
    assert active_thread["id"] == roll_data["thread_id"]
    assert session_data["last_rolled_result"] == roll_data["result"]

    history_response = await auth_client.get("/api/v1/sessions/")
    assert history_response.status_code == 200
    history_data = history_response.json()
    assert "sessions" in history_data
    history_sessions = history_data["sessions"]
    assert history_sessions
    latest = history_sessions[0]
    assert latest["id"] == session_data["id"]
    assert latest["last_rolled_result"] == roll_data["result"]
    assert latest["active_thread"]["id"] == roll_data["thread_id"]

    rate_response = await auth_client.post(
        "/api/v1/rate/",
        json={"rating": 5.0, "issues_read": 1, "finish_session": False},
    )
    assert rate_response.status_code == 200

    session_after_rate = await auth_client.get("/api/v1/sessions/current/")
    assert session_after_rate.status_code == 200
    rated_data = session_after_rate.json()

    expected_die = step_down(roll_data["die_size"])
    assert rated_data["current_die"] == expected_die

    # After rating with Save & Continue, no new pending target is auto-selected.
    assert rated_data["pending_thread_id"] is None
    assert rated_data["active_thread"] is None
    assert rated_data["last_rolled_result"] is None

    # Regression check: rating again without a new roll is blocked.
    second_rate = await auth_client.post(
        "/api/v1/rate/",
        json={"rating": 4.5, "issues_read": 1, "finish_session": False},
    )
    assert second_rate.status_code == 400
    assert "No active thread" in second_rate.json()["detail"]


@pytest.mark.parametrize("automatic_die", [6, 12])
@pytest.mark.parametrize("action", ["rate", "snooze"])
async def test_manual_die_keeps_history_truthful_and_resumes_auto(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User,
    automatic_die: int, action: str,
) -> None:
    """Manual actions record d20 without advancing the suspended automatic ladder."""
    from app.models import Event, ReadingSession

    thread = Thread(title="Manual die regression", format="Comic", issues_remaining=5,
                    queue_position=1, status="active", user_id=default_user.id)
    session = ReadingSession(start_die=6, user_id=default_user.id)
    async_db.add_all([thread, session])
    await async_db.flush()
    session_id = session.id
    async_db.add(Event(type="rate", session_id=session_id, die=10, die_after=automatic_die))
    await async_db.commit()

    selected = await auth_client.post("/api/v1/roll/set-die", params={"die": 20})
    assert selected.status_code == 200
    for _ in range(2 if action == "rate" else 1):
        rolled = await auth_client.post("/api/v1/roll/")
        assert rolled.status_code == 200, rolled.text
        assert rolled.json()["die_size"] == 20
        response = await auth_client.post(
            f"/api/v1/{action}/",
            json={"rating": 2.0, "issues_read": 1, "finish_session": False}
            if action == "rate" else None,
        )
        assert response.status_code == 200, response.text
        current = await auth_client.get("/api/v1/sessions/current/")
        assert current.json()["manual_die"] == 20
        assert current.json()["current_die"] == 20
        assert current.json()["ladder_path"].endswith("20")

    details = await auth_client.get(f"/api/v1/sessions/{session_id}/details")
    assert details.status_code == 200
    outcome = next(event for event in details.json()["events"] if event["type"] == action
                   and event["thread_title"] == thread.title)
    assert outcome["die"] == 20
    assert outcome["die_after"] == 20
    if action == "rate":
        snapshots = await auth_client.get(f"/api/v1/sessions/{session_id}/snapshots")
        assert snapshots.status_code == 200
        snapshot_id = snapshots.json()["snapshots"][0]["id"]
        undone = await auth_client.post(f"/api/v1/undo/{session_id}/undo/{snapshot_id}")
        assert undone.status_code == 200, undone.text
        assert undone.json()["current_die"] == 20
        assert undone.json()["manual_die"] == 20
    cleared = await auth_client.post("/api/v1/roll/clear-manual-die")
    assert cleared.status_code == 200
    assert cleared.text == f"d{automatic_die}"
    current = await auth_client.get("/api/v1/sessions/current/")
    assert current.json()["manual_die"] is None
    assert current.json()["current_die"] == automatic_die
    history = await auth_client.get("/api/v1/sessions/")
    item = next(row for row in history.json()["sessions"] if row["id"] == session_id)
    assert item["current_die"] == automatic_die
