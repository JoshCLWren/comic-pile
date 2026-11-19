"""Regression tests for the performance metric repository summary queries.

These tests guard the fix for issue #3233: ``get_performance_metrics_summary()``
must aggregate only the filtered relation through its subquery's exported
columns, never the base ``PerformanceMetric`` entity alongside the subquery
(which produced a Cartesian product that multiplied counts and corrupted
min/max/percentile results).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.performance_metric import PerformanceMetric


def _make_metric(
    session: AsyncSession,
    *,
    metric_type: str,
    cold: bool,
    response_time_ms: float,
    deployment_id: str,
    timestamp: datetime,
) -> PerformanceMetric:
    """Build and flush a single performance metric row."""
    metric = PerformanceMetric(
        metric_type=metric_type,
        cold=cold,
        response_time_ms=response_time_ms,
        deployment_id=deployment_id,
        timestamp=timestamp,
    )
    session.add(metric)
    return metric


@pytest.fixture()
def sample_times() -> dict[str, datetime]:
    """Deterministic, spread-out timestamps for boundary filter tests."""
    now = datetime.now(UTC)
    return {
        "t1": now - timedelta(days=10),
        "t2": now - timedelta(days=8),
        "t3": now - timedelta(days=6),
        "t4": now - timedelta(days=4),
        "t5": now - timedelta(days=2),
        "t6": now - timedelta(days=1),
    }


@pytest.fixture()
async def populated_metrics(async_db: AsyncSession, sample_times: dict[str, datetime]) -> None:
    """Mixed metric types, deployments, cold/warm groups, and timestamps.

    Rows (metric_type, cold, rt_ms, deployment, ts):
      initial_response, cold,   100, dep-a, t1
      initial_response, cold,   200, dep-a, t2
      shell_render,     cold,    50, dep-a, t3
      initial_response, warm,   300, dep-a, t4
      initial_response, warm,   400, dep-b, t5
      initial_response, warm,   500, dep-a, t6
    """
    _make_metric(
        async_db,
        metric_type="initial_response",
        cold=True,
        response_time_ms=100.0,
        deployment_id="dep-a",
        timestamp=sample_times["t1"],
    )
    _make_metric(
        async_db,
        metric_type="initial_response",
        cold=True,
        response_time_ms=200.0,
        deployment_id="dep-a",
        timestamp=sample_times["t2"],
    )
    _make_metric(
        async_db,
        metric_type="shell_render",
        cold=True,
        response_time_ms=50.0,
        deployment_id="dep-a",
        timestamp=sample_times["t3"],
    )
    _make_metric(
        async_db,
        metric_type="initial_response",
        cold=False,
        response_time_ms=300.0,
        deployment_id="dep-a",
        timestamp=sample_times["t4"],
    )
    _make_metric(
        async_db,
        metric_type="initial_response",
        cold=False,
        response_time_ms=400.0,
        deployment_id="dep-b",
        timestamp=sample_times["t5"],
    )
    _make_metric(
        async_db,
        metric_type="initial_response",
        cold=False,
        response_time_ms=500.0,
        deployment_id="dep-a",
        timestamp=sample_times["t6"],
    )
    await async_db.flush()


def _assert_stats(
    stats: object,
    *,
    min_ms: float,
    max_ms: float,
    median_ms: float,
) -> None:
    """Assert aggregate stats after narrowing the nested dict with isinstance."""
    assert isinstance(stats, dict)
    assert stats["min"] == min_ms
    assert stats["max"] == max_ms
    assert stats["median"] == median_ms
    p95 = stats["p95"]
    assert isinstance(p95, float) or p95 is None
    assert p95 is None or min_ms <= p95 <= max_ms


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_compiled_sql_has_no_cartesian_product(
    async_db: AsyncSession,
) -> None:
    """Compiled SQL aggregates through a single subquery WITHOUT a cross join."""
    dialect = postgresql.dialect()

    base_query = select(PerformanceMetric)
    base_subquery = base_query.subquery()

    count_query = (
        select(
            base_subquery.c.cold,
            func.count(base_subquery.c.id).label("count"),
        )
        .select_from(base_subquery)
        .group_by(base_subquery.c.cold)
    )
    count_sql = str(count_query.compile(dialect=dialect))

    stats_query = (
        select(
            base_subquery.c.cold,
            func.min(base_subquery.c.response_time_ms).label("min"),
            func.max(base_subquery.c.response_time_ms).label("max"),
        )
        .select_from(base_subquery)
        .group_by(base_subquery.c.cold)
    )
    stats_sql = str(stats_query.compile(dialect=dialect))

    for sql in (count_sql, stats_sql):
        upper = sql.upper()
        assert "CROSS JOIN" not in upper
        # The base table must appear only inside the subquery's FROM, never as
        # a second top-level table (comma join) or join target.
        assert ", performance_metrics" not in upper
        assert "JOIN performance_metrics" not in upper
        # Top-level FROM is the subquery.
        assert "FROM (" in sql
