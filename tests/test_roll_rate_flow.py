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

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()

    session_after_roll = await auth_client.get("/api/sessions/current/")
    assert session_after_roll.status_code == 200
    session_data = session_after_roll.json()

    active_thread = session_data.get("active_thread")
    assert active_thread is not None
    assert active_thread["id"] == roll_data["thread_id"]
    assert session_data["last_rolled_result"] == roll_data["result"]

    history_response = await auth_client.get("/api/sessions/")
    assert history_response.status_code == 200
    history_sessions = history_response.json()
    assert history_sessions
    latest = history_sessions[0]
    assert latest["id"] == session_data["id"]
    assert latest["last_rolled_result"] == roll_data["result"]
    assert latest["active_thread"]["id"] == roll_data["thread_id"]

    rate_response = await auth_client.post(
        "/api/rate/",
        json={"rating": 5.0, "issues_read": 1, "finish_session": False},
    )
    assert rate_response.status_code == 200

    session_after_rate = await auth_client.get("/api/sessions/current/")
    assert session_after_rate.status_code == 200
    rated_data = session_after_rate.json()

    expected_die = step_down(roll_data["die_size"])
    assert rated_data["current_die"] == expected_die
    # After rating, a new roll event is created for the next available thread
    # The active_thread and last_rolled_result are from the most recent roll event
    assert rated_data["active_thread"] is not None
    assert rated_data["active_thread"]["id"] in [t.id for t in threads]
    assert rated_data["last_rolled_result"] is not None
