"""Session management functions."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Settings
from app.models import Session as SessionModel


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware and in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


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
    started_at = _ensure_utc(session.started_at)
    return started_at >= cutoff_time and session.ended_at is None


def should_start_new(db: Session) -> bool:
    """Check if no active session in configured gap hours."""
    settings = _get_settings(db)
    cutoff_time = datetime.now(UTC) - timedelta(hours=settings.session_gap_hours)
    cutoff_time_naive = cutoff_time.replace(tzinfo=None)
    recent_sessions = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.started_at >= cutoff_time_naive)
            .where(SessionModel.ended_at.is_(None))
        )
        .scalars()
        .all()
    )

    return len(recent_sessions) == 0


def get_or_create(db: Session, user_id: int) -> SessionModel:
    """Get active session or create new one."""
    settings = _get_settings(db)
    cutoff_time = datetime.now(UTC) - timedelta(hours=settings.session_gap_hours)
    cutoff_time_naive = cutoff_time.replace(tzinfo=None)
    active_session = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.ended_at.is_(None))
            .where(SessionModel.started_at >= cutoff_time_naive)
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

    return new_session


def end_session(session_id: int, db: Session) -> None:
    """Mark session as ended."""
    session = db.get(SessionModel, session_id)
    if session:
        session.ended_at = datetime.now(UTC)
        db.commit()


def get_current_die(session_id: int, db: Session) -> int:
    """Get current die size based on last rating event in session."""
    settings = _get_settings(db)
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

    session = db.get(SessionModel, session_id)
    return session.start_die if session else settings.start_die
