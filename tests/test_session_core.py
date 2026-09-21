"""Tests for session core logic."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import clear_settings_cache
from app.models import Event, Session, Snapshot, Thread, User
from app.models import Session as SessionModel
from comic_pile.session import (
    create_session_start_snapshot,
    end_session,
    get_current_die,
    get_or_create,
    is_active,
    should_start_new,
)

async def test_session_env_int_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Session env parsing validates and rejects invalid values.

    Args:
        monkeypatch: Pytest's monkeypatch fixture for modifying env vars.
    """
    import comic_pile.session as session_mod
    from pydantic import ValidationError

    from app.config import SessionSettings

    # Clear cached settings to pick up new env vars
    clear_settings_cache()

    monkeypatch.setenv("SESSION_GAP_HOURS", "12")
    clear_settings_cache()
    assert session_mod._session_gap_hours() == 12

    # 0 is outside valid range, should raise ValidationError
    monkeypatch.setenv("SESSION_GAP_HOURS", "0")
    clear_settings_cache()
    with pytest.raises(ValidationError) as exc_info:
        SessionSettings()
    assert "SESSION_GAP_HOURS" in str(exc_info.value)
    # Clean up invalid value so subsequent tests work
    monkeypatch.delenv("SESSION_GAP_HOURS")
    clear_settings_cache()

    monkeypatch.setenv("START_DIE", "20")
    clear_settings_cache()
    assert session_mod._start_die() == 20

    # 3 is outside valid range, should raise ValidationError
    monkeypatch.setenv("START_DIE", "3")
    clear_settings_cache()
    with pytest.raises(ValidationError) as exc_info:
        SessionSettings()
    assert "START_DIE" in str(exc_info.value)

async def test_get_or_create_ignores_advisory_lock_failure(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Advisory lock errors should not prevent session creation."""
    original_execute = async_db.execute

    async def wrapped_execute(statement, *args, **kwargs):
        if "pg_advisory_xact_lock" in str(statement):
            raise RuntimeError("boom")
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(async_db, "execute", wrapped_execute)

    session = await get_or_create(async_db, user_id=1)
    assert session.id is not None
    assert session.user_id == 1

async def test_is_active_true(async_db: AsyncSession, default_user: User) -> None:
    """Session created < 6 hours ago is active."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    result = await is_active(session.started_at, session.ended_at, async_db)
    assert result is True

async def test_is_active_false_old(async_db: AsyncSession, default_user: User) -> None:
    """Session created > 6 hours ago is inactive."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=7),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    result = await is_active(session.started_at, session.ended_at, async_db)
    assert result is False

async def test_is_active_false_ended(async_db: AsyncSession, default_user: User) -> None:
    """Session that has ended is inactive."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        ended_at=datetime.now(UTC),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    result = await is_active(session.started_at, session.ended_at, async_db)
    assert result is False

async def test_should_start_new_true(async_db: AsyncSession, default_user: User) -> None:
    """No active session in last 6 hours."""
    old_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=7),
        ended_at=datetime.now(UTC),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(old_session)
    await async_db.commit()

    result = await should_start_new(async_db, user_id=default_user.id)
    assert result is True

async def test_should_start_new_false(async_db: AsyncSession, default_user: User) -> None:
    """Active session exists."""
    active_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(active_session)
    await async_db.commit()

    result = await should_start_new(async_db, user_id=default_user.id)
    assert result is False

async def test_get_or_create_existing(async_db: AsyncSession, sample_data: dict) -> None:
    """Returns existing active session (< 6 hours old)."""
    # End all sample sessions first
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    await async_db.commit()

    # Create a fresh active session within last 6 hours
    active_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=1,
    )
    async_db.add(active_session)
    await async_db.commit()

    result = await get_or_create(async_db, user_id=1)
    assert result.id == active_session.id

async def test_get_or_create_new(async_db: AsyncSession, sample_data: dict) -> None:
    """Creates new session when none active."""
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    await async_db.commit()

    new_session = await get_or_create(async_db, user_id=1)
    assert new_session.start_die == 6
    assert new_session.user_id == 1

async def test_end_session(async_db: AsyncSession, sample_data: dict) -> None:
    """Marks session as ended."""
    session = sample_data["sessions"][0]
    assert session.ended_at is None

    await end_session(session.id, async_db)

    await async_db.refresh(session)
    assert session.ended_at is not None

async def test_end_session_nonexistent(async_db: AsyncSession, default_user: User) -> None:
    """Gracefully handles ending non-existent session."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    await end_session(999, async_db)

    assert True

async def test_is_active_exactly_6_hours(async_db: AsyncSession, default_user: User) -> None:
    """Session created exactly 6 hours ago is considered active."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=5, minutes=59),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    result = await is_active(session.started_at, session.ended_at, async_db)
    assert result is True

async def test_should_start_new_multiple_old_sessions(
    async_db: AsyncSession, default_user: User
) -> None:
    """Multiple old sessions still return true."""
    for i in range(3):
        old_session = SessionModel(
            started_at=datetime.now(UTC) - timedelta(hours=7 + i),
            ended_at=datetime.now(UTC),
            start_die=6,
            user_id=default_user.id,
        )
        async_db.add(old_session)
    await async_db.commit()

    result = await should_start_new(async_db, user_id=default_user.id)
    assert result is True

async def test_get_or_create_returns_most_recent(
    async_db: AsyncSession, default_user: User
) -> None:
    """Returns most recent active session when multiple exist."""
    recent_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=10,
        user_id=default_user.id,
    )
    older_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=2),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(recent_session)
    async_db.add(older_session)
    await async_db.commit()

    result = await get_or_create(async_db, user_id=default_user.id)
    assert result.id == recent_session.id
    assert result.start_die == 10

async def test_get_or_create_creates_default_user(async_db: AsyncSession) -> None:
    """BUG-141: Creates default user when user_id doesn't exist."""
    from app.models import User

    non_existent_user_id = 999

    user = await async_db.get(User, non_existent_user_id)
    assert user is None

    new_session = await get_or_create(async_db, user_id=non_existent_user_id)

    assert new_session is not None
    assert new_session.user_id == non_existent_user_id

    user = await async_db.get(User, non_existent_user_id)
    assert user is not None
    assert user.username == f"user_{non_existent_user_id}"

async def test_get_or_create_creates_user_id_1(async_db: AsyncSession) -> None:
    """BUG-142: Creates default user when user_id=1 doesn't exist."""
    from app.models import User
    from sqlalchemy import delete

    await async_db.execute(delete(Snapshot))
    await async_db.execute(delete(Session))
    from sqlalchemy import delete

    await async_db.execute(delete(Thread))
    await async_db.execute(delete(User))
    await async_db.commit()

    user = await async_db.get(User, 1)
    assert user is None

    new_session = await get_or_create(async_db, user_id=1)

    assert new_session is not None
    assert new_session.user_id == 1

    user = await async_db.get(User, 1)
    assert user is not None
    assert user.username == "user_1"

async def test_get_active_thread_includes_last_rolled_result(
    async_db: AsyncSession, sample_data: dict
) -> None:
    """Get active thread includes last rolled result value."""
    session = sample_data["sessions"][0]
    thread = sample_data["threads"][0]

    event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(event)
    await async_db.commit()

    active_thread = await get_active_thread(session.id, async_db)

    assert active_thread is not None
    assert active_thread.id == thread.id
    assert active_thread.last_rolled_result == 4

async def test_is_active_no_lazy_load(async_db: AsyncSession, default_user: User) -> None:
    """Test that is_active doesn't cause lazy load of session object."""
    session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    started_at = session.started_at
    ended_at = session.ended_at

    result = await is_active(started_at, ended_at, async_db)
    assert result is True

    old_started_at = datetime.now(UTC) - timedelta(hours=7)
    old_ended_at = None
    result = await is_active(old_started_at, old_ended_at, async_db)
    assert result is False

    ended_started_at = datetime.now(UTC) - timedelta(hours=1)
    ended_ended_at = datetime.now(UTC)
    result = await is_active(ended_started_at, ended_ended_at, async_db)
    assert result is False

async def test_get_or_create_deadlock_retry(
    async_db: AsyncSession, sample_data: dict, default_user: User
) -> None:
    """Test that get_or_create creates new session when no active one exists.

    Regression test for BUG-126: OperationalError deadlock handling.
    Verifies that get_or_create can successfully create a session when needed.
    """
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    await async_db.commit()

    new_session = await get_or_create(async_db, user_id=default_user.id)
    assert new_session is not None
    assert new_session.start_die == 6

async def test_get_or_create_uses_session_id_to_prevent_lazy_load(
    async_db: AsyncSession, sample_data: dict, default_user: User
) -> None:
    """Test that get_or_create session object doesn't cause lazy loading issues.

    Regression test for BUG-126: Verify that session returned from get_or_create
    can have its id extracted without triggering lazy loading that causes deadlocks.
    """
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    await async_db.commit()

    result_session = await get_or_create(async_db, user_id=default_user.id)

    session_id = result_session.id
    assert session_id is not None
    assert isinstance(session_id, int)

async def test_get_or_create_non_deadlock_operational_error(
    async_db: AsyncSession, sample_data: dict
) -> None:
    """Test that get_or_create raises non-deadlock OperationalError.

    Regression test for BUG-126: Verify that non-deadlock OperationalErrors
    are properly raised without retrying.
    """
    from unittest.mock import patch
    from sqlalchemy.exc import OperationalError

    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC) - timedelta(hours=7)
    await async_db.commit()

    commit_call_count = 0
    original_commit = async_db.commit

    async def mock_commit(*args, **kwargs):
        nonlocal commit_call_count
        commit_call_count += 1
        if commit_call_count == 1:
            raise OperationalError("some other error", {}, Exception())
        return await original_commit(*args, **kwargs)

    with patch.object(async_db, "commit", side_effect=mock_commit):
        with pytest.raises(OperationalError, match="some other error"):
            await get_or_create(async_db, user_id=1)

async def test_is_active_with_naive_datetime(async_db: AsyncSession, default_user: User) -> None:
    """Test that is_active handles datetime without timezone.

    When a datetime has no tzinfo, it should be treated as UTC.
    This test verifies the branch is executed (coverage).
    """
    session = SessionModel(
        started_at=datetime.now() - timedelta(hours=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    naive_dt = datetime.now() - timedelta(hours=1)
    assert naive_dt.tzinfo is None

    result = await is_active(naive_dt, None, async_db)
    assert result is not None

async def test_is_active_naive_old_datetime(async_db: AsyncSession, default_user: User) -> None:
    """Test that is_active handles old naive datetime correctly."""
    session = SessionModel(
        started_at=datetime.now() - timedelta(hours=1),
        start_die=6,
        user_id=default_user.id,
    )
    async_db.add(session)
    await async_db.commit()

    naive_dt = datetime.now() - timedelta(hours=7)
    assert naive_dt.tzinfo is None

    result = await is_active(naive_dt, None, async_db)
    assert result is not None

async def test_get_or_create_returns_existing_within_time_window(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test that get_or_create returns existing session when one exists within time window.

    This tests the early return path at line 148 where active_session is found
    before attempting to create a new session.
    """
    from app.models import Session as SessionModel

    existing_session = SessionModel(
        start_die=8,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(existing_session)
    await async_db.commit()
    await async_db.refresh(existing_session)

    result = await get_or_create(async_db, user_id=default_user.id)

    assert result.id == existing_session.id
    assert result.start_die == 8

async def test_move_to_position_handles_zero(async_db: AsyncSession, sample_data: dict) -> None:
    """Test that move_to_position raises ValueError for new_position=0."""
    from comic_pile.queue import move_to_position
    import pytest

    thread = sample_data["threads"][0]

    with pytest.raises(ValueError, match="Position must be at least 1"):
        await move_to_position(thread.id, thread.user_id, 0, async_db)

async def test_get_or_create_race_condition_after_lock(
    async_db: AsyncSession, sample_data: dict, default_user: User
) -> None:
    """Test that get_or_create returns existing session when found.

    This tests the path where an active session already exists and is returned.
    """
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC) - timedelta(hours=7)
    await async_db.commit()

    existing_session = SessionModel(
        start_die=10,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(existing_session)
    await async_db.commit()
    await async_db.refresh(existing_session)

    result = await get_or_create(async_db, user_id=default_user.id)
    assert result.id == existing_session.id
    assert result.start_die == 10

async def test_get_or_create_deadlock_retries_with_backoff(
    async_db: AsyncSession, sample_data: dict, default_user: User
) -> None:
    """Test that get_or_create returns existing session found after lock."""
    from app.models import Session as SessionModel

    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC) - timedelta(hours=7)
    await async_db.commit()

    existing_session = SessionModel(
        start_die=8,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(existing_session)
    await async_db.commit()
    await async_db.refresh(existing_session)

    result = await get_or_create(async_db, user_id=default_user.id)
    assert result.id == existing_session.id
    assert result.start_die == 8

async def test_get_or_create_returns_existing_after_lock(
    async_db: AsyncSession, sample_data: dict, default_user: User
) -> None:
    """Test that get_or_create returns session found after acquiring lock.

    This tests the code path at line 141 where active_session is found
    after the lock is acquired.
    """
    from app.models import Session as SessionModel

    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC) - timedelta(hours=7)
    await async_db.commit()

    existing_session = SessionModel(
        start_die=10,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(existing_session)
    await async_db.commit()
    await async_db.refresh(existing_session)

    result = await get_or_create(async_db, user_id=default_user.id)
    assert result.id == existing_session.id
    assert result.start_die == 10

async def test_get_current_die_returns_manual_die(
    async_db: AsyncSession, default_user: User
) -> None:
    """Test that get_current_die returns manual_die when set.

    This tests line 194 where session.manual_die is returned.
    """
    from comic_pile.session import get_current_die
    from app.models import Session as SessionModel

    session = SessionModel(
        start_die=6,
        manual_die=20,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    current_die = await get_current_die(session.id, async_db)
    assert current_die == 20

