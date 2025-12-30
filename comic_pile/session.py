"""Session management functions."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Session as SessionModel


def is_active(session: SessionModel) -> bool:
    """Check if session was within last 6 hours."""
    cutoff_time = datetime.now() - timedelta(hours=6)
    return session.started_at >= cutoff_time and session.ended_at is None


def should_start_new(db: Session) -> bool:
    """Check if no active session in last 6 hours."""
    cutoff_time = datetime.now() - timedelta(hours=6)
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


def get_or_create(db: Session, thread_id: int) -> SessionModel:
    """Get active session or create new one."""
    active_session = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.ended_at.is_(None))
            .order_by(SessionModel.started_at.desc())
        )
        .scalars()
        .first()
    )

    if active_session:
        return active_session

    new_session = SessionModel(thread_id=thread_id, die_size=6, ladder_path="[6]")
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    return new_session


def end_session(session_id: int, db: Session) -> None:
    """Mark session as ended."""
    session = db.get(SessionModel, session_id)
    if session:
        session.ended_at = datetime.now()
        db.commit()
