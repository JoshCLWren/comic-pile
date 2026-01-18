"""Session management functions."""

import os
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel


_session_creation_lock = threading.Lock()


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        parsed = int(value)
    except ValueError:
        return default

    return parsed


def _session_gap_hours() -> int:
    hours = _int_env("SESSION_GAP_HOURS", 6)
    return hours if 1 <= hours <= 168 else 6


def _start_die() -> int:
    die = _int_env("START_DIE", 6)
    return die if 4 <= die <= 20 else 6


def is_active(started_at: datetime, ended_at: datetime | None, _db: Session) -> bool:
    """Check if session was within configured gap hours."""
    cutoff_time = datetime.now(UTC) - timedelta(hours=_session_gap_hours())
    session_time = started_at
    if session_time.tzinfo is None:
        session_time = session_time.replace(tzinfo=UTC)
    return session_time >= cutoff_time and ended_at is None


def should_start_new(db: Session) -> bool:
    """Check if no active session in configured gap hours."""
    cutoff_time = datetime.now(UTC) - timedelta(hours=_session_gap_hours())
    recent_sessions = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.started_at >= cutoff_time)
            .where(SessionModel.ended_at.is_(None))
        )
        .scalars()
        .all()
    )

    return len(recent_sessions) == 0


def create_session_start_snapshot(db: Session, session: SessionModel) -> None:
    """Create a snapshot of all states at session start."""
    threads = db.execute(select(Thread)).scalars().all()

    thread_states = {}
    for thread in threads:
        thread_states[thread.id] = {
            "title": thread.title,
            "format": thread.format,
            "issues_remaining": thread.issues_remaining,
            "last_rating": thread.last_rating,
            "last_activity_at": thread.last_activity_at.isoformat()
            if thread.last_activity_at
            else None,
            "queue_position": thread.queue_position,
            "status": thread.status,
            "review_url": thread.review_url,
            "last_review_at": thread.last_review_at.isoformat() if thread.last_review_at else None,
            "notes": thread.notes,
            "is_test": thread.is_test,
            "created_at": thread.created_at.isoformat(),
            "user_id": thread.user_id,
        }

    session_state = {
        "start_die": session.start_die,
        "manual_die": session.manual_die,
    }

    snapshot = Snapshot(
        session_id=session.id,
        event_id=None,
        thread_states=thread_states,
        description="Session start",
    )
    snapshot.session_state = session_state
    db.add(snapshot)
    db.commit()


def get_or_create(db: Session, user_id: int) -> SessionModel:
    """Get active session or create new one."""
    from app.models import User

    max_retries = 3
    initial_delay = 0.1
    retries = 0

    while retries < max_retries:
        try:
            session_gap_hours = _session_gap_hours()
            start_die = _start_die()

            user = db.get(User, user_id)
            if not user:
                user = User(id=user_id, username="default_user")
                db.add(user)
                db.commit()
                db.refresh(user)

            cutoff_time = datetime.now(UTC) - timedelta(hours=session_gap_hours)
            active_session = (
                db.execute(
                    select(SessionModel)
                    .where(SessionModel.ended_at.is_(None))
                    .where(SessionModel.started_at >= cutoff_time)
                    .order_by(SessionModel.started_at.desc(), SessionModel.id.desc())
                )
                .scalars()
                .first()
            )

            if active_session:
                return active_session

            with _session_creation_lock:
                try:
                    db.execute(text("SELECT pg_advisory_xact_lock(12345)"))
                except Exception:
                    pass

                active_session = (
                    db.execute(
                        select(SessionModel)
                        .where(SessionModel.ended_at.is_(None))
                        .where(SessionModel.started_at >= cutoff_time)
                        .order_by(SessionModel.started_at.desc(), SessionModel.id.desc())
                    )
                    .scalars()
                    .first()
                )

                if active_session:
                    return active_session

                new_session = SessionModel(start_die=start_die, user_id=user_id)
                db.add(new_session)
                db.commit()
                db.refresh(new_session)

                create_session_start_snapshot(db, new_session)

                return new_session
        except OperationalError as e:
            if "deadlock" in str(e).lower():
                db.rollback()
                retries += 1
                if retries >= max_retries:
                    raise RuntimeError(
                        f"Failed to get_or_create session after {max_retries} retries"
                    ) from e
                delay = initial_delay * (2 ** (retries - 1))
                time.sleep(delay)
            else:
                raise

    raise RuntimeError(f"Failed to get_or_create session after {max_retries} retries")


def end_session(session_id: int, db: Session) -> None:
    """Mark session as ended."""
    session = db.get(SessionModel, session_id)
    if session:
        session.ended_at = datetime.now(UTC)
        db.commit()


def get_current_die(session_id: int, db: Session) -> int:
    """Get current die size based on manual selection or last rating event."""
    start_die = _start_die()
    session = db.get(SessionModel, session_id)

    if session and session.manual_die:
        return session.manual_die

    last_rate_event = (
        db.execute(
            select(Event)
            .where(Event.session_id == session_id)
            .where(Event.type == "rate")
            .where(Event.die_after.is_not(None))
            .order_by(Event.timestamp.desc())
        )
        .scalars()
        .first()
    )

    if last_rate_event:
        die_after = last_rate_event.die_after
        return die_after if die_after is not None else start_die

    return session.start_die if session else start_die
