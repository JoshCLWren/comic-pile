"""Analytics response schemas for comic reading metrics.

The metrics surface moved from an untyped router-level ``dict`` to these typed
Pydantic models so every field is validated and documented in the OpenAPI
schema. Field names and shapes are unchanged from the legacy payload so
existing clients and the route-versioning alias contract keep working.
"""

from pydantic import BaseModel


class RecentSession(BaseModel):
    """Summary of one recent reading session."""

    id: int
    started_at: str
    ended_at: str | None
    start_die: int


class TopRatedThread(BaseModel):
    """Summary of one highly rated thread."""

    id: int
    title: str
    rating: float
    format: str
    issues_remaining: int | None = None
    issues_remaining: int | None = None


class AnalyticsMetricsResponse(BaseModel):
    """Reading metrics and analytics for the current user.

    ``completion_rate`` and ``average_session_hours`` keep the legacy
    ``int | float`` shape because the aggregation returns either an exact
    integer fallback (0) or a rounded float.
    """

    total_threads: int
    active_threads: int
    completed_threads: int
    completion_rate: int | float
    average_session_hours: int | float
    recent_sessions: list[RecentSession]
    event_stats: dict[str, int]
    top_rated_threads: list[TopRatedThread]
