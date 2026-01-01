"""Tests for session logic."""

from datetime import datetime, timedelta

from app.models import Session as SessionModel
from app.models import Thread
from comic_pile.session import end_session, get_or_create, is_active, should_start_new


def test_is_active_true(db):
    """Session created < 6 hours ago is active."""
    session = SessionModel(
        started_at=datetime.now() - timedelta(hours=1),
        start_die=6,
        user_id=1,
    )
    db.add(session)
    db.commit()

    result = is_active(session)
    assert result is True


def test_is_active_false_old(db):
    """Session created > 6 hours ago is inactive."""
    session = SessionModel(
        started_at=datetime.now() - timedelta(hours=7),
        start_die=6,
        user_id=1,
    )
    db.add(session)
    db.commit()

    result = is_active(session)
    assert result is False


def test_is_active_false_ended(db):
    """Session that has ended is inactive."""
    session = SessionModel(
        started_at=datetime.now() - timedelta(hours=1),
        ended_at=datetime.now(),
        start_die=6,
        user_id=1,
    )
    db.add(session)
    db.commit()

    result = is_active(session)
    assert result is False


def test_should_start_new_true(db):
    """No active session in last 6 hours."""
    old_session = SessionModel(
        started_at=datetime.now() - timedelta(hours=7),
        ended_at=datetime.now(),
        start_die=6,
        user_id=1,
    )
    db.add(old_session)
    db.commit()

    result = should_start_new(db)
    assert result is True


def test_should_start_new_false(db):
    """Active session exists."""
    active_session = SessionModel(
        started_at=datetime.now() - timedelta(hours=1),
        start_die=6,
        user_id=1,
    )
    db.add(active_session)
    db.commit()

    result = should_start_new(db)
    assert result is False


def test_get_or_create_existing(db, sample_data):
    """Returns existing active session (< 6 hours old)."""
    # End all sample sessions first
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now()
    db.commit()

    # Create a fresh active session within last 6 hours
    active_session = SessionModel(
        started_at=datetime.now() - timedelta(hours=1),
        start_die=6,
        user_id=1,
    )
    db.add(active_session)
    db.commit()

    result = get_or_create(db, user_id=1)
    assert result.id == active_session.id


def test_get_or_create_new(db, sample_data):
    """Creates new session when none active."""
    for session in sample_data["sessions"]:
        session.ended_at = datetime.now()
    db.commit()

    new_session = get_or_create(db, user_id=1)
    assert new_session.start_die == 6
    assert new_session.user_id == 1


def test_end_session(db, sample_data):
    """Marks session as ended."""
    session = sample_data["sessions"][0]
    assert session.ended_at is None

    end_session(session.id, db)

    db.refresh(session)
    assert session.ended_at is not None


def test_end_session_nonexistent(db, sample_data):
    """Gracefully handles ending non-existent session."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
        created_at=datetime.now(),
    )
    db.add(thread)
    db.commit()

    end_session(999, db)

    assert True


def test_is_active_exactly_6_hours(db):
    """Session created exactly 6 hours ago is considered active."""
    session = SessionModel(
        started_at=datetime.now() - timedelta(hours=5, minutes=59),
        start_die=6,
        user_id=1,
    )
    db.add(session)
    db.commit()

    result = is_active(session)
    assert result is True


def test_should_start_new_multiple_old_sessions(db):
    """Multiple old sessions still return true."""
    for i in range(3):
        old_session = SessionModel(
            started_at=datetime.now() - timedelta(hours=7 + i),
            ended_at=datetime.now(),
            start_die=6,
            user_id=1,
        )
        db.add(old_session)
    db.commit()

    result = should_start_new(db)
    assert result is True


def test_get_or_create_returns_most_recent(db):
    """Returns most recent active session when multiple exist."""
    recent_session = SessionModel(
        started_at=datetime.now() - timedelta(hours=1),
        start_die=10,
        user_id=1,
    )
    older_session = SessionModel(
        started_at=datetime.now() - timedelta(hours=2),
        start_die=6,
        user_id=1,
    )
    db.add(recent_session)
    db.add(older_session)
    db.commit()

    result = get_or_create(db, user_id=1)
    assert result.id == recent_session.id
    assert result.start_die == 10
