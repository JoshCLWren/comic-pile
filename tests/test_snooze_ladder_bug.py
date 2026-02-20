"""Test for snooze + roll ladder bug.

Reproduces the issue where multiple snooze operations followed by a rating
cause incorrect die ladder behavior due to manual_die not being cleared.
"""

from datetime import UTC, datetime
from sqlalchemy import select

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread
from app.models import Session as SessionModel, User
from httpx import AsyncClient
from comic_pile.dice_ladder import step_down, step_up


@pytest.mark.asyncio
async def test_multiple_snooze_then_rate(auth_client: AsyncClient, async_db: AsyncSession, default_user: User) -> None:
    """Reproduce bug: multiple snoozes followed by rating causes incorrect die.

    Based on user's session log:
    - Start at d6
    - Roll and snooze (should step up to d8)
    - Roll and snooze (should step up to d10)
    - Roll and snooze (should step up to d12)
    - Roll and snooze (should step up to d20)
    - Roll and snooze (should stay at d20, max)
    - Roll and rate 4.0/5.0 (should step down to d12)

    Expected ladder path: 6 → 8 → 10 → 12 → 20 → 20 → 12
    But due to bug, goes to: 6 → 4 (incorrect)
    """
    now = datetime.now(UTC)

    threads = [
        Thread(
            title="Superman: All Star Superman",
            format="Comic",
            issues_remaining=5,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Wolverine: Larry Hama run",
            format="Comic",
            issues_remaining=4,
            queue_position=2,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Starman: James Robison and Starman related comics",
            format="Comic",
            issues_remaining=3,
            queue_position=3,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Micronauts: Michael golden run",
            format="Comic",
            issues_remaining=4,
            queue_position=4,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Doom patrol",
            format="Comic",
            issues_remaining=3,
            queue_position=5,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="conan saga: Conan readthrough",
            format="Comic",
            issues_remaining=4,
            queue_position=6,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
    ]

    for thread in threads:
        async_db.add(thread)
    await async_db.commit()

    expected_dies = [6]

    for i, _thread in enumerate(threads[:6]):
        roll_response = await auth_client.post("/api/roll/")
        assert roll_response.status_code == 200

        if i == 0:
            result = await async_db.execute(
                select(SessionModel).where(SessionModel.user_id == default_user.id)
            )
            session = result.scalars().first()
            assert session is not None
            assert session.start_die == 6

        if i < 5:
            snooze_response = await auth_client.post("/api/snooze/")
            assert snooze_response.status_code == 200
            snooze_data = snooze_response.json()

            current_die = snooze_data["current_die"]
            expected_die = step_up(expected_dies[-1])
            expected_dies.append(expected_die)

            assert current_die == expected_die, (
                f"After snooze #{i + 1}, expected die d{expected_die}, got d{current_die}"
            )

    rate_response = await auth_client.post(
        "/api/rate/",
        json={"rating": 4.0, "issues_read": 1, "finish_session": False},
    )
    assert rate_response.status_code == 200

    session_after_rate = await auth_client.get("/api/sessions/current/")
    assert session_after_rate.status_code == 200
    rated_data = session_after_rate.json()

    expected_final_die = step_down(20)
    actual_final_die = rated_data["current_die"]

    assert actual_final_die == expected_final_die, (
        f"After rating 4.0/5.0 from d20, expected die d{expected_final_die}, "
        f"got d{actual_final_die}. Expected ladder path: {' → '.join(str(d) for d in expected_dies)} → {expected_final_die}"
    )
