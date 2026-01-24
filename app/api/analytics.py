"""Analytics API endpoints for comic reading metrics."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Event, Thread
from app.models import Session as SessionModel
from app.models.user import User

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/metrics")
def get_metrics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Get reading metrics and analytics for the current user.

    Returns:
        Dictionary containing various reading metrics and statistics
    """
    # Total threads
    total_threads = (
        db.scalar(select(func.count(Thread.id)).where(Thread.user_id == current_user.id)) or 0
    )

    # Active threads
    active_threads = (
        db.scalar(
            select(func.count(Thread.id)).where(
                Thread.user_id == current_user.id, Thread.status == "active"
            )
        )
        or 0
    )

    # Completed threads
    completed_threads = (
        db.scalar(
            select(func.count(Thread.id)).where(
                Thread.user_id == current_user.id, Thread.status == "completed"
            )
        )
        or 0
    )

    # Completion rate
    completion_rate = (
        round((completed_threads / total_threads) * 100, 1) if total_threads > 0 else 0
    )

    # Average session duration (in hours)
    avg_duration_result = db.execute(
        select(
            func.avg(func.extract("epoch", SessionModel.ended_at - SessionModel.started_at) / 3600)
        ).where(
            SessionModel.user_id == current_user.id,
            SessionModel.ended_at.isnot(None),
        )
    ).scalar()

    avg_session_hours = round(avg_duration_result, 1) if avg_duration_result is not None else 0

    # Recent reading sessions (last 7 days)
    seven_days_ago = datetime.now(UTC) - timedelta(days=7)
    recent_sessions = db.scalars(
        select(SessionModel)
        .where(
            SessionModel.user_id == current_user.id,
            SessionModel.started_at >= seven_days_ago,
        )
        .order_by(SessionModel.started_at.desc())
        .limit(5)
    ).all()

    # Reading events by type
    event_counts = db.execute(
        select(Event.type, func.count(Event.id))
        .join(SessionModel, Event.session_id == SessionModel.id)
        .where(SessionModel.user_id == current_user.id)
        .group_by(Event.type)
    ).all()

    event_stats: dict[str, int] = {}
    for event_type, count in event_counts:
        event_stats[event_type] = count

    # Top rated threads (rating >= 4.0)
    top_threads = db.scalars(
        select(Thread)
        .where(
            Thread.user_id == current_user.id,
            Thread.last_rating.isnot(None),
            Thread.last_rating >= 4.0,
        )
        .order_by(Thread.last_rating.desc())
        .limit(5)
    ).all()

    return {
        "total_threads": total_threads or 0,
        "active_threads": active_threads or 0,
        "completed_threads": completed_threads or 0,
        "completion_rate": completion_rate,
        "average_session_hours": avg_session_hours,
        "recent_sessions": [
            {
                "id": session.id,
                "started_at": session.started_at.isoformat(),
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "start_die": session.start_die,
            }
            for session in recent_sessions
        ],
        "event_stats": event_stats,
        "top_rated_threads": [
            {
                "id": thread.id,
                "title": thread.title,
                "rating": thread.last_rating,
                "format": thread.format,
            }
            for thread in top_threads
        ],
    }
