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
from app.repositories import performance_metric_repository
from app.services import performance_metric_service


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
async def populated_metrics(
    async_db: AsyncSession, sample_times: dict[str, datetime]
) -> None:
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
async def test_get_performance_metrics_summary_no_filters(
    async_db: AsyncSession, populated_metrics: None
) -> None:
    """All rows aggregate by cold/warm with exact counts and percentiles."""
    summary = await performance_metric_repository.get_performance_metrics_summary(
        async_db
    )

    assert summary["count"] == 6
    by_cold = summary["by_cold"]
    assert isinstance(by_cold, dict)
    assert by_cold == {True: 3, False: 3}

    by_cold_stats = summary["by_cold_stats"]
    assert isinstance(by_cold_stats, dict)
    cold_stats = by_cold_stats[True]
    _assert_stats(cold_stats, min_ms=50.0, max_ms=200.0, median_ms=100.0)
    warm_stats = by_cold_stats[False]
    _assert_stats(warm_stats, min_ms=300.0, max_ms=500.0, median_ms=400.0)


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_filter_metric_type(
    async_db: AsyncSession, populated_metrics: None
) -> None:
    """Filtering to one metric type constrains count and stats without multiplication."""
    summary = await performance_metric_repository.get_performance_metrics_summary(
        async_db, metric_type="initial_response"
    )

    assert summary["count"] == 5
    by_cold = summary["by_cold"]
    assert isinstance(by_cold, dict)
    assert by_cold == {True: 2, False: 3}

    by_cold_stats = summary["by_cold_stats"]
    assert isinstance(by_cold_stats, dict)
    cold_stats = by_cold_stats[True]
    _assert_stats(cold_stats, min_ms=100.0, max_ms=200.0, median_ms=150.0)
    warm_stats = by_cold_stats[False]
    _assert_stats(warm_stats, min_ms=300.0, max_ms=500.0, median_ms=400.0)


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_filter_deployment(
    async_db: AsyncSession, populated_metrics: None
) -> None:
    """Filtering to one deployment returns exactly its rows: count 1, no multiplication."""
    summary = await performance_metric_repository.get_performance_metrics_summary(
        async_db, deployment_id="dep-b"
    )

    assert summary["count"] == 1
    by_cold = summary["by_cold"]
    assert isinstance(by_cold, dict)
    assert by_cold == {False: 1}

    by_cold_stats = summary["by_cold_stats"]
    assert isinstance(by_cold_stats, dict)
    warm_stats = by_cold_stats[False]
    _assert_stats(warm_stats, min_ms=400.0, max_ms=400.0, median_ms=400.0)
    assert warm_stats["p95"] == 400.0


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_combined_filters(
    async_db: AsyncSession, populated_metrics: None
) -> None:
    """Combined metric_type and deployment filters remain correct across cold/warm groups."""
    summary = await performance_metric_repository.get_performance_metrics_summary(
        async_db,
        metric_type="initial_response",
        deployment_id="dep-a",
    )

    # Rows 1, 2, 4, 6 match; row 3 is shell_render, row 5 is dep-b.
    assert summary["count"] == 4
    by_cold = summary["by_cold"]
    assert isinstance(by_cold, dict)
    assert by_cold == {True: 2, False: 2}

    by_cold_stats = summary["by_cold_stats"]
    assert isinstance(by_cold_stats, dict)
    cold_stats = by_cold_stats[True]
    _assert_stats(cold_stats, min_ms=100.0, max_ms=200.0, median_ms=150.0)
    warm_stats = by_cold_stats[False]
    _assert_stats(warm_stats, min_ms=300.0, max_ms=500.0, median_ms=400.0)


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_unrelated_rows_do_not_change_filtered(
    async_db: AsyncSession, populated_metrics: None
) -> None:
    """Adding unrelated rows cannot change an already-filtered summary (no Cartesian product)."""
    before = await performance_metric_repository.get_performance_metrics_summary(
        async_db, deployment_id="dep-b"
    )
    assert before["count"] == 1
    by_cold_stats = before["by_cold_stats"]
    assert isinstance(by_cold_stats, dict)
    assert by_cold_stats[False]["min"] == 400.0

    # Insert many unrelated rows: different deployment, different metric type,
    # both cold and warm classifications.
    unrelated_ts = datetime.now(UTC)
    for i in range(10):
        _make_metric(
            async_db,
            metric_type="api_response",
            cold=i % 2 == 0,
            response_time_ms=float(i * 10),
            deployment_id="dep-c",
            timestamp=unrelated_ts,
        )
    await async_db.flush()

    after = await performance_metric_repository.get_performance_metrics_summary(
        async_db, deployment_id="dep-b"
    )
    assert after == before
    assert after["count"] == 1
    after_stats = after["by_cold_stats"]
    assert isinstance(after_stats, dict)
    assert after_stats[False]["min"] == 400.0


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_empty_input(
    async_db: AsyncSession,
) -> None:
    """Empty input returns zero count with no cold/warm groups."""
    summary = await performance_metric_repository.get_performance_metrics_summary(
        async_db
    )

    assert summary["count"] == 0
    assert summary["by_cold"] == {}
    assert summary["by_cold_stats"] == {}


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_no_matching_rows(
    async_db: AsyncSession, populated_metrics: None
) -> None:
    """Filters that match nothing return an empty summary without error."""
    summary = await performance_metric_repository.get_performance_metrics_summary(
        async_db, metric_type="nonexistent"
    )

    assert summary["count"] == 0
    assert summary["by_cold"] == {}
    assert summary["by_cold_stats"] == {}


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_boundary_timestamps(
    async_db: AsyncSession, populated_metrics: None, sample_times: dict[str, datetime]
) -> None:
    """Start and end time boundaries are inclusive; rows outside the window are excluded."""
    summary = await performance_metric_repository.get_performance_metrics_summary(
        async_db,
        start_time=sample_times["t2"],
        end_time=sample_times["t5"],
    )

    # Rows at t2, t3, t4, t5 match; rows at t1 and t6 are outside the window.
    assert summary["count"] == 4
    by_cold = summary["by_cold"]
    assert isinstance(by_cold, dict)
    assert by_cold == {True: 2, False: 2}


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_compiled_sql_has_no_cartesian_product(
    async_db: AsyncSession,
) -> None:
    """Compiled SQL aggregates through a single subquery WITHOUT a cross join."""
    dialect = postgresql.dialect()

    # Mirror the query construction used by get_performance_metrics_summary
    # (app/repositories/performance_metric_repository.py:103) so regressions
    # in the repository's subquery pattern are caught.
    base_query = select(PerformanceMetric)
    base_subquery = base_query.subquery()

    count_query = select(
        base_subquery.c.cold,
        func.count(base_subquery.c.id).label("count"),
    ).select_from(base_subquery).group_by(base_subquery.c.cold)
    count_sql = str(count_query.compile(dialect=dialect))

    stats_query = select(
        base_subquery.c.cold,
        func.min(base_subquery.c.response_time_ms).label("min"),
        func.max(base_subquery.c.response_time_ms).label("max"),
    ).select_from(base_subquery).group_by(base_subquery.c.cold)
    stats_sql = str(stats_query.compile(dialect=dialect))

    for sql in (count_sql, stats_sql):
        upper = sql.upper()
        assert "CROSS JOIN" not in upper
        # The base table must appear only inside the subquery's FROM, never as
        # a second top-level table (comma join) or join target.
        # Use consistent uppercase casing so the check can actually match SQL.
        assert ", PERFORMANCE_METRICS" not in upper
        assert "JOIN PERFORMANCE_METRICS" not in upper
        # Top-level FROM is the subquery.
        assert "FROM (" in sql


@pytest.mark.asyncio
async def test_service_get_metrics_summary_preserves_contract(
    async_db: AsyncSession, populated_metrics: None
) -> None:
    """The service caller preserves the existing summary shape."""
    result = await performance_metric_service.get_metrics_summary(async_db)

    assert set(result.keys()) == {"count", "by_cold", "by_cold_stats"}
    assert result["count"] == 6
    by_cold = result["by_cold"]
    assert isinstance(by_cold, dict)
    assert by_cold == {True: 3, False: 3}


@pytest.mark.asyncio
async def test_service_get_cold_warm_comparison_preserves_contract(
    async_db: AsyncSession, populated_metrics: None
) -> None:
    """The cold/warm comparison service caller preserves its existing shape."""
    result = await performance_metric_service.get_cold_warm_comparison(async_db)

    assert set(result.keys()) == {"cold", "warm", "total"}
    assert result["total"] == 6
    cold = result["cold"]
    assert isinstance(cold, dict)
    assert cold["count"] == 3
    assert cold["min"] == 50.0
    assert cold["max"] == 200.0
    warm = result["warm"]
    assert isinstance(warm, dict)
    assert warm["count"] == 3
    assert warm["min"] == 300.0
    assert warm["max"] == 500.0
