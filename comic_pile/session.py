"""Session management functions."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Settings, Snapshot, Thread
from app.models import Session as SessionModel


def _get_settings(db: Session) -> Settings:
    """Get settings record, creating with defaults if needed."""
    settings = db.execute(select(Settings)).scalars().first()
    if not settings:
        settings = Settings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def is_active(session: SessionModel, db: Session) -> bool:
    """Check if session was within configured gap hours."""
    settings = _get_settings(db)
    cutoff_time = datetime.now(UTC) - timedelta(hours=settings.session_gap_hours)
    session_time = session.started_at
    if session_time.tzinfo is None:
        session_time = session_time.replace(tzinfo=UTC)
    return session_time >= cutoff_time and session.ended_at is None


def should_start_new(db: Session) -> bool:
    """Check if no active session in configured gap hours."""
    settings = _get_settings(db)
    cutoff_time = datetime.now(UTC) - timedelta(hours=settings.session_gap_hours)
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
    settings = _get_settings(db)
    cutoff_time = datetime.now(UTC) - timedelta(hours=settings.session_gap_hours)
    active_session = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.ended_at.is_(None))
            .where(SessionModel.started_at >= cutoff_time)
            .order_by(SessionModel.started_at.desc())
        )
        .scalars()
        .first()
    )

    if active_session:
        return active_session

    new_session = SessionModel(start_die=settings.start_die, user_id=user_id)
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    create_session_start_snapshot(db, new_session)

    return new_session


def end_session(session_id: int, db: Session) -> None:
    """Mark session as ended."""
    session = db.get(SessionModel, session_id)
    if session:
        session.ended_at = datetime.now(UTC)
        db.commit()


def get_current_die(session_id: int, db: Session) -> int:
    """Get current die size based on manual selection or last rating event."""
    settings = _get_settings(db)
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
        return die_after if die_after is not None else settings.start_die

    return session.start_die if session else settings.start_die
