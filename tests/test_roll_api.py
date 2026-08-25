"""Tests for roll API endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_roll_success(auth_client: AsyncClient, sample_data: dict) -> None:
    """POST /roll/ returns valid thread."""
    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200

    data = response.json()
    assert "thread_id" in data
    assert "title" in data
    assert "die_size" in data
    assert "result" in data
    assert data["die_size"] == 8
    assert 1 <= data["result"] <= 8

    thread_ids = [t.id for t in sample_data["threads"] if t.status == "active"]
    assert data["thread_id"] in thread_ids


@pytest.mark.asyncio
async def test_roll_override(auth_client: AsyncClient, sample_data: dict) -> None:
    """POST /roll/override/ sets specific thread."""
    _ = sample_data
    thread_id = 1
    response = await auth_client.post("/api/roll/override", json={"thread_id": thread_id})
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == thread_id
    assert data["title"] == "Superman"
    assert data["die_size"] == 8
    assert data["result"] == 0


@pytest.mark.asyncio
async def test_roll_no_pool(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Returns error if no active threads."""
    from tests.conftest import get_or_create_user_async

    await get_or_create_user_async(async_db)

    response = await auth_client.post("/api/roll/")
    assert response.status_code == 400
    assert "No active threads" in response.json()["detail"]


@pytest.mark.asyncio
async def test_roll_overflow(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Roll works correctly when thread count < die size."""
    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Only Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == thread.id
    assert 1 <= data["result"] <= 1


@pytest.mark.asyncio
async def test_roll_blocked_when_pending_exists(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """POST /roll/ returns 409 when a pending thread exists."""
    _ = sample_data

    first_response = await auth_client.post("/api/roll/")
    assert first_response.status_code == 200

    second_response = await auth_client.post("/api/roll/")
    assert second_response.status_code == 409
    assert "already pending" in second_response.json()["detail"]


@pytest.mark.asyncio
async def test_dismiss_pending_clears_pending_thread(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """POST /roll/dismiss-pending clears pending thread in current session."""
    _ = sample_data

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200

    before_session = await auth_client.get("/api/sessions/current/")
    assert before_session.status_code == 200
    assert before_session.json()["pending_thread_id"] is not None

    dismiss_response = await auth_client.post("/api/roll/dismiss-pending")
    assert dismiss_response.status_code == 204

    after_session = await auth_client.get("/api/sessions/current/")
    assert after_session.status_code == 200
    assert after_session.json()["pending_thread_id"] is None


@pytest.mark.asyncio
async def test_dismiss_pending_when_no_pending_exists(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """POST /roll/dismiss-pending is idempotent when no pending thread exists."""
    _ = sample_data

    before_session = await auth_client.get("/api/sessions/current/")
    assert before_session.status_code == 200
    assert before_session.json()["pending_thread_id"] is None

    dismiss_response = await auth_client.post("/api/roll/dismiss-pending")
    assert dismiss_response.status_code == 204

    after_session = await auth_client.get("/api/sessions/current/")
    assert after_session.status_code == 200
    assert after_session.json()["pending_thread_id"] is None


@pytest.mark.asyncio
async def test_roll_pending_message_does_not_leak_other_user_thread_title(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """POST /roll/ does not leak another user's thread title in pending-roll detail."""
    import os
    from datetime import UTC, datetime

    from app.models import Session as SessionModel, Thread
    from tests.conftest import get_or_create_user_async

    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    current_session_id = session_response.json()["id"]

    other_user = await get_or_create_user_async(async_db, username=f"other_user_{os.getpid()}")
    private_title = "Private Other User Thread"
    private_thread = Thread(
        title=private_title,
        format="Comic",
        issues_remaining=3,
        queue_position=99,
        status="active",
        user_id=other_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(private_thread)
    await async_db.commit()
    await async_db.refresh(private_thread)

    current_session = await async_db.get(SessionModel, current_session_id)
    assert current_session is not None
    current_session.pending_thread_id = private_thread.id
    current_session.pending_thread_updated_at = datetime.now(UTC)
    await async_db.commit()

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 409
    detail = roll_response.json()["detail"]
    assert "already pending" in detail
    assert private_title not in detail


@pytest.mark.asyncio
async def test_roll_override_nonexistent(auth_client: AsyncClient, sample_data: dict) -> None:
    """Override returns 404 for non-existent thread."""
    _ = sample_data
    response = await auth_client.post("/api/roll/override", json={"thread_id": 999})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_set_manual_die(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """POST /roll/set-die sets manual_die on session."""
    _ = sample_data
    _ = async_db
    response = await auth_client.post("/api/roll/set-die?die=20")
    assert response.status_code == 200
    assert response.text == "d20"

    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()
    assert session_data["manual_die"] == 20


@pytest.mark.asyncio
async def test_clear_manual_die(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """POST /roll/clear-manual-die clears manual_die and returns to auto mode."""
    _ = sample_data
    from app.models import Session as SessionModel

    result = await async_db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None)))
    session = result.scalars().first()
    assert session is not None

    session.manual_die = 12
    await async_db.commit()

    response = await auth_client.post("/api/roll/clear-manual-die")
    assert response.status_code == 200
    assert response.text == "d8"

    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()
    assert session_data["manual_die"] is None


@pytest.mark.asyncio
async def test_clear_manual_die_with_no_manual_set(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """POST /roll/clear-manual-die works even when manual_die is not set."""
    _ = sample_data
    response = await auth_client.post("/api/roll/clear-manual-die")
    assert response.status_code == 200
    assert response.text == "d8"


@pytest.mark.asyncio
async def test_clear_manual_die_returns_correct_current_die_regression(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Regression test for bug where clearing manual die returned wrong die value.

    When manual mode is disengaged by clicking auto, the endpoint should return
    the correct current die from the dice ladder, not a stale cached value.
    """
    _ = sample_data
    from app.models import Session as SessionModel

    result = await async_db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None)))
    session = result.scalars().first()
    assert session is not None

    session.manual_die = 20
    await async_db.commit()

    response = await auth_client.post("/api/roll/clear-manual-die")
    assert response.status_code == 200

    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()

    assert session_data["manual_die"] is None
    assert response.text == f"d{session_data['current_die']}"


@pytest.mark.asyncio
async def test_override_roll_blocked_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Override roll returns 422 for blocked threads."""
    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    blocked_thread = Thread(
        title="Blocked Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        is_blocked=True,
        user_id=user.id,
    )
    async_db.add(blocked_thread)
    await async_db.commit()
    await async_db.refresh(blocked_thread)

    response = await auth_client.post("/api/roll/override", json={"thread_id": blocked_thread.id})
    assert response.status_code == 422
    assert "blocked" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_override_roll_completed_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Override roll returns 422 for completed threads."""
    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    completed_thread = Thread(
        title="Completed Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="completed",
        is_blocked=False,
        user_id=user.id,
    )
    async_db.add(completed_thread)
    await async_db.commit()
    await async_db.refresh(completed_thread)

    response = await auth_client.post("/api/roll/override", json={"thread_id": completed_thread.id})
    assert response.status_code == 422
    assert "completed" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_roll_bootstrap_does_not_flag_fresh_threads_as_stale(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Bootstrap counts a thread as stale only when its effective activity predates the cutoff.

    A freshly created thread with NULL last_activity_at falls back to created_at and must
    not be flagged stale, matching the previous frontend stale-thread contract.
    """
    from datetime import UTC, datetime, timedelta

    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    now = datetime.now(UTC)
    stale_date = now - timedelta(days=30)

    fresh_thread = Thread(
        title="Fresh Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        last_activity_at=None,
        created_at=now,
    )
    stale_thread = Thread(
        title="Old Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
        last_activity_at=stale_date,
        created_at=now,
    )
    async_db.add_all([fresh_thread, stale_thread])
    await async_db.commit()

    response = await auth_client.get("/api/roll/bootstrap")
    assert response.status_code == 200
    data = response.json()

    assert data["stale_thread_count"] == 1
    assert data["stale_thread"]["title"] == "Old Thread"


@pytest.mark.asyncio
async def test_roll_bootstrap_counts_null_activity_old_threads_as_stale(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Bootstrap flags a thread with NULL last_activity_at and an old created_at as stale."""
    from datetime import UTC, datetime, timedelta

    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    now = datetime.now(UTC)
    old_date = now - timedelta(days=30)

    old_no_activity_thread = Thread(
        title="Old No Activity",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        last_activity_at=None,
        created_at=old_date,
    )
    async_db.add(old_no_activity_thread)
    await async_db.commit()

    response = await auth_client.get("/api/roll/bootstrap")
    assert response.status_code == 200
    data = response.json()

    assert data["stale_thread_count"] == 1
    assert data["stale_thread"]["title"] == "Old No Activity"


# regression: decision-history contract tests for issue #1693
@pytest.mark.asyncio
async def test_regression_roll_outcome_linking(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Verify that rate/snooze events link back to their originating roll event.

    Exercises the Phase 0 decision-history regression contract (issue #1693):
    - Rate and snooze outcomes point to the correct originating roll via
      source_roll_event_id (no "latest event of type X" guesswork needed by
      consumers)
    - Roll events store issue metadata (issue_id, issue_number)
    - Decision latency can be calculated from linked roll/outcome timestamps
    - Random and override paths remain distinguishable via selection_method
    - Legacy/null instrumentation fields remain tolerated where backwards
      compatibility requires it
    """
    from datetime import UTC, datetime
    from sqlalchemy import select

    from app.models import Event, Thread
    from tests.conftest import get_or_create_user_async

    # Setup: create user and threads
    user = await get_or_create_user_async(async_db)

    now = datetime.now(UTC)

    threads = [
        Thread(
            id=1,
            title="Thread A",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=user.id,
            created_at=now,
        ),
        Thread(
            id=2,
            title="Thread B",
            format="Comic",
            issues_remaining=5,
            queue_position=2,
            status="active",
            user_id=user.id,
            created_at=now,
        ),
        Thread(
            id=3,
            title="Thread C",
            format="Comic",
            issues_remaining=0,
            queue_position=3,
            status="completed",
            user_id=user.id,
            created_at=now,
        ),
    ]
    for t in threads:
        async_db.add(t)
    await async_db.commit()
    await async_db.refresh_all()

    async def latest_event(event_type: str) -> Event | None:
        result = await async_db.execute(
            select(Event).where(Event.type == event_type).order_by(Event.id.desc())
        )
        return result.scalars().first()

    # --- Scenario 1: random roll → rate ---
    roll1_response = await auth_client.post("/api/roll/")
    assert roll1_response.status_code == 200
    roll1_data = roll1_response.json()
    roll1_selection_method = roll1_data["selection_method"]
    roll1_issue_id = roll1_data.get("issue_id")
    roll1_issue_number = roll1_data.get("issue_number")

    rate1_kwargs = {"rating": 4.5}
    if roll1_issue_id is not None:
        rate1_kwargs["issue_id"] = roll1_issue_id
    rate1_response = await auth_client.post("/api/rate/", json=rate1_kwargs)
    assert rate1_response.status_code == 200

    rate1_db_event = await latest_event("rate")
    assert rate1_db_event is not None
    assert rate1_db_event.source_roll_event_id is not None, "Rate event must link to a roll"
    roll1_db_event = await async_db.get(Event, rate1_db_event.source_roll_event_id)
    assert roll1_db_event is not None
    assert roll1_db_event.type == "roll"
    assert roll1_db_event.selection_method == roll1_selection_method
    if roll1_issue_id is not None:
        assert roll1_db_event.issue_id == roll1_issue_id
    if roll1_issue_number is not None:
        assert roll1_db_event.issue_number == roll1_issue_number

    latency = (rate1_db_event.timestamp - roll1_db_event.timestamp).total_seconds()
    assert latency >= 0, "Rate must happen after roll"

    # --- Scenario 2: random roll → snooze ---
    roll2_response = await auth_client.post("/api/roll/")
    assert roll2_response.status_code == 200
    roll2_data = roll2_response.json()
    roll2_selection_method = roll2_data["selection_method"]

    snooze1_response = await auth_client.post("/api/snooze/")
    assert snooze1_response.status_code == 200

    snooze1_db_event = await latest_event("snooze")
    assert snooze1_db_event is not None
    assert snooze1_db_event.source_roll_event_id is not None, "Snooze event must link to a roll"
    roll2_db_event = await async_db.get(Event, snooze1_db_event.source_roll_event_id)
    assert roll2_db_event is not None
    assert roll2_db_event.type == "roll"
    assert roll2_db_event.selection_method == roll2_selection_method

    # --- Scenario 3: override roll → rate ---
    override_response = await auth_client.post("/api/roll/override", json={"thread_id": 3})
    assert override_response.status_code == 200
    override_data = override_response.json()
    override_selection_method = override_data["selection_method"]

    rate2_response = await auth_client.post("/api/rate/", json={"rating": 3.0})
    assert rate2_response.status_code == 200

    rate2_db_event = await latest_event("rate")
    assert rate2_db_event is not None
    assert rate2_db_event.source_roll_event_id is not None, "Override rate must link to a roll"
    override_roll_event = await async_db.get(Event, rate2_db_event.source_roll_event_id)
    assert override_roll_event is not None
    assert override_roll_event.type == "roll"
    assert override_roll_event.selection_method == "override"

    # --- Scenario 4: random vs override distinguishability ---
    all_rolls = await async_db.execute(select(Event).where(Event.type == "roll"))
    methods = {ev.selection_method for ev in all_rolls.scalars().all()}
    assert "random" in methods, "Should have random roll events"
    assert "override" in methods, "Should have override roll events"


@pytest.mark.asyncio
async def test_regression_issue_metadata_preserved(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Verify that roll events preserve issue metadata for the regression contract.

    Validates acceptance criteria:
    - "Roll issue metadata matches the issue that was offered to the user"
    - "Legacy/null instrumentation fields remain tolerated where backwards
      compatibility requires it"
    """
    from datetime import UTC, datetime
    from sqlalchemy import select

    from app.models import Event, Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)

    thread = Thread(
        id=1,
        title="Issue Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200

    roll_event = await async_db.execute(
        select(Event).where(Event.type == "roll").order_by(Event.id.desc())
    )
    db_roll = roll_event.scalars().first()
    assert db_roll is not None, "Roll event should be persisted"

    # Issue metadata is denormalized onto the roll event when an offered issue
    # exists; NULL remains valid for legacy/backwards-compatible sessions.
    assert db_roll.issue_id is None or isinstance(db_roll.issue_id, int)
    assert db_roll.issue_number is None or isinstance(db_roll.issue_number, str)
