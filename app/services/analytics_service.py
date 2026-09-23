"""Analytics metric aggregation for the reading metrics surface.

The service owns the aggregation rules (completion rate, formatting, recent
session trimming) that used to live in the router. Query construction and
execution live in ``app/repositories/analytics_repository.py``; the router
delegates here and maps the result to an ``AnalyticsMetricsResponse``.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.thread import normalize_format_value
from app.repositories import analytics_repository as analytics_repo
from app.schemas.analytics import (
    AnalyticsMetricsResponse,
    RecentSession,
    TopRatedThread,
)

RECENT_SESSIONS_WINDOW = timedelta(days=7)


class AnalyticsService:
    """Aggregate reading metrics for one user."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the service with a database session.

        Args:
            db: Async database session.
        """
        self._db = db

    async def get_metrics(self, user_id: int) -> AnalyticsMetricsResponse:
        """Compute the metrics overview for the current user.

        Args:
            user_id: The authenticated user identifier.

        Returns:
            Typed metrics payload covering thread counts, rating activity,
            recent sessions, event distribution, and top-rated threads.
        """
        total_threads = await analytics_repo.count_threads(self._db, user_id)
        active_threads = await analytics_repo.count_threads(
            self._db, user_id, status="active"
        )
        completed_threads = await analytics_repo.count_threads(
            self._db, user_id, status="completed"
        )

        completion_rate = (
            round((completed_threads / total_threads) * 100, 1)
            if total_threads > 0
            else 0
        )

        avg_session_hours = await analytics_repo.average_session_hours(self._db, user_id)

        window_start = datetime.now(UTC) - RECENT_SESSIONS_WINDOW
        recent = await analytics_repo.recent_sessions(
            self._db,
            user_id,
            since=window_start,
        )

        event_stats = await analytics_repo.event_type_counts(self._db, user_id)
        top_threads = await analytics_repo.top_rated_threads(self._db, user_id)

        return AnalyticsMetricsResponse(
            total_threads=total_threads,
            active_threads=active_threads,
            completed_threads=completed_threads,
            completion_rate=completion_rate,
            average_session_hours=avg_session_hours,
            recent_sessions=[
                RecentSession(
                    id=session.id,
                    started_at=session.started_at.isoformat(),
                    ended_at=session.ended_at.isoformat() if session.ended_at else None,
                    start_die=session.start_die,
                )
                for session in recent
            ],
            event_stats=event_stats,
            top_rated_threads=[
                TopRatedThread(
                    id=thread.id,
                    title=thread.title,
                    rating=thread.last_rating if thread.last_rating is not None else 0.0,
                    format=normalize_format_value(thread.format),
                    issues_remaining=thread.issues_remaining,
                )
                for thread in top_threads
            ],
        )
