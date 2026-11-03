"""API tests for the typed analytics metrics surface.

Issue #2598 moved the analytics metrics aggregation out of the router into an
analytics service + repository and replaced the untyped ``dict`` response with
``AnalyticsMetricsResponse``. These tests verify the response contract, the
aggregation values, and the router/service/repository layering.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread, User
from app.schemas.analytics import AnalyticsMetricsResponse

EXPECTED_FIELDS = {
    "total_threads",
    "active_threads",
    "completed_threads",
    "completion_rate",
    "average_session_hours",
    "recent_sessions",
    "event_stats",
    "top_rated_threads",
}


@pytest.mark.asyncio
async def test_metrics_response_is_typed_schema(
    auth_client: AsyncClient,
    sample_data: dict,
) -> None:
    """The endpoint returns every legacy field and validates as the schema."""
    response = await auth_client.get("/api/analytics/metrics")
    assert response.status_code == 200

    payload = response.json()
    assert set(payload) == EXPECTED_FIELDS
    validated = AnalyticsMetricsResponse.model_validate(payload)
    assert validated.total_threads == 5
    assert validated.active_threads == 4
    assert validated.completed_threads == 1
    assert validated.completion_rate == 20.0
    assert validated.average_session_hours == 0
    assert len(validated.recent_sessions) == 2
    assert validated.event_stats == {"roll": 1, "rate": 1}


@pytest.mark.asyncio
async def test_metrics_aggregates_recent_sessions_and_ended_duration(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict,
) -> None:
    """Recent sessions honor the window and the average uses ended durations."""
    sessions = sample_data["sessions"]
    now = datetime.now(UTC)
    sessions[0].started_at = now - timedelta(days=1)
    sessions[0].ended_at = sessions[0].started_at + timedelta(hours=2)
    sessions[1].started_at = now
    await async_db.flush()

    response = await auth_client.get("/api/analytics/metrics")
    assert response.status_code == 200
    payload = response.json()

    assert payload["average_session_hours"] == 2.0
    recent = payload["recent_sessions"]
    assert [row["id"] for row in recent] == [sessions[1].id, sessions[0].id]
    assert recent[0]["ended_at"] is None
    assert recent[0]["started_at"] == now.isoformat()
    assert recent[0]["start_die"] == sessions[1].start_die


@pytest.mark.asyncio
async def test_metrics_top_rated_threads_ordered_and_normalized(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict,
) -> None:
    """Top-rated threads are ordered and formats are canonicalized."""
    threads = sample_data["threads"]
    superman, _, _, flash, aquaman = threads
    superman.last_rating = 4.2
    flash.last_rating = 4.9
    flash.format = "digital"
    aquaman.last_rating = 3.5
    await async_db.flush()

    response = await auth_client.get("/api/analytics/metrics")
    assert response.status_code == 200
    top = response.json()["top_rated_threads"]

    assert [(row["id"], row["rating"]) for row in top] == [
        (flash.id, 4.9),
        (superman.id, 4.2),
    ]
    assert top[0]["title"] == flash.title
    assert top[0]["format"] == "Digital"
    assert top[1]["format"] == "Comic"


@pytest.mark.asyncio
async def test_metrics_empty_user_returns_zero_defaults(
    auth_client: AsyncClient,
) -> None:
    """A user with no data receives safe zero defaults, not errors."""
    response = await auth_client.get("/api/analytics/metrics")
    assert response.status_code == 200
    payload = response.json()

    assert payload["total_threads"] == 0
    assert payload["active_threads"] == 0
    assert payload["completed_threads"] == 0
    assert payload["completion_rate"] == 0
    assert payload["average_session_hours"] == 0
    assert payload["recent_sessions"] == []
    assert payload["event_stats"] == {}
    assert payload["top_rated_threads"] == []
    AnalyticsMetricsResponse.model_validate(payload)


@pytest.mark.asyncio
async def test_metrics_scopes_data_to_authenticated_user(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict,
) -> None:
    """Another user's highly rated threads never leak into the metrics."""
    other_user = User(
        username="analytics-other-user",
        created_at=datetime.now(UTC),
    )
    async_db.add(other_user)
    await async_db.flush()

    async_db.add(
        Thread(
            title="Foreign Thread",
            format="Comic",
            issues_remaining=3,
            queue_position=99,
            status="active",
            last_rating=5.0,
            user_id=other_user.id,
            created_at=datetime.now(UTC),
        )
    )
    await async_db.flush()

    response = await auth_client.get("/api/analytics/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_threads"] == 5
    assert payload["active_threads"] == 4
    assert payload["completed_threads"] == 1
    assert payload["top_rated_threads"] == []
    assert payload["event_stats"] == {"roll": 1, "rate": 1}


def test_analytics_router_has_no_layering_violations() -> None:
    """The router no longer builds queries, so the baseline can drop it."""
    from tests.test_router_layering_conformance import (
        ROUTERS_DIR,
        scan_router_source,
    )

    source = (ROUTERS_DIR / "analytics.py").read_text(encoding="utf-8")
    assert scan_router_source(source) == set()
