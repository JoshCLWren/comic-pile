"""Tests for performance metric summary query fixes.

This module tests the fix for issue #3233, which addresses a Cartesian
product bug in ``get_performance_metrics_summary()``. The old queries
aggregated a filtered ``select(PerformanceMetric)`` subquery while still
reading columns from the entity, so SQLAlchemy emitted
``FROM (subquery), performance_metrics``: every matching row was paired with
every row in the table, multiplying counts and inflating min/max/percentiles.

Coverage combines three layers:

* exact filtered values (counts, min/max/median/p95) against a populated fixture,
* multiplication resistance: filtering to one row stays at one row no matter how
  many unrelated rows exist,
* compiled-SQL and ``EXPLAIN`` evidence that both aggregate statements read a
  single ``performance_metrics`` source with no join.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, UTC, timedelta
from typing import Any, cast

import pytest
from sqlalchemy import Select, Table, event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.performance_metric import PerformanceMetric
from app.repositories import performance_metric_repository
from app.services import performance_metric_service


def _summary_parts(
    summary: dict[str, object],
) -> tuple[dict[bool, int], dict[bool, dict[str, float | None]]]:
    """Narrow the summary payload into its concrete cold/warm structures.

    Args:
        summary: Payload returned by ``get_performance_metrics_summary``.

    Returns:
        Tuple of the cold/warm counts and the cold/warm response-time stats.
    """
    return (
        cast(dict[bool, int], summary["by_cold"]),
        cast(dict[bool, dict[str, float | None]], summary["by_cold_stats"]),
    )


@contextmanager
def _captured_statements(db: AsyncSession) -> Iterator[list[Select[Any]]]:
    """Collect the SELECT statements the session executes inside the block.

    Args:
        db: Session whose engine emits the statements.

    Yields:
        List that receives every executed ``Select`` in execution order.
    """
    captured: list[Select[Any]] = []

    def _record(conn, clauseelement, multiparams, params) -> None:
        if isinstance(clauseelement, Select):
            captured.append(clauseelement)

    engine = db.get_bind().engine
    event.listen(engine, "before_execute", _record)
    try:
        yield captured
    finally:
        event.remove(engine, "before_execute", _record)


async def _explain(db: AsyncSession, statement: Select[Any]) -> str:
    """Return the PostgreSQL plan text for one captured statement.

    Args:
        db: Session used to run ``EXPLAIN``.
        statement: Statement captured from the session.

    Returns:
        Newline-joined ``EXPLAIN`` output rows.
    """
    literal_sql = str(
        statement.compile(
            dialect=postgresql.dialect(paramstyle="numeric"),
            compile_kwargs={"literal_binds": True},
        )
    )
    result = await db.execute(text(f"EXPLAIN {literal_sql}"))
    return "\n".join(str(row[0]) for row in result)


@pytest.fixture
async def sample_performance_metrics(db) -> list[PerformanceMetric]:
    """Create a diverse set of performance metrics for testing.

    Returns:
        List of created PerformanceMetric instances.
    """
    now = datetime.now(UTC)
    metrics = [
        # Metric type A - Cold
        PerformanceMetric(
            metric_type="initial_response",
            cold=True,
            response_time_ms=100.0,
            deployment_id="deploy-1",
            timestamp=now - timedelta(hours=1),
        ),
        PerformanceMetric(
            metric_type="initial_response",
            cold=True,
            response_time_ms=150.0,
            deployment_id="deploy-1",
            timestamp=now - timedelta(minutes=30),
        ),
        PerformanceMetric(
            metric_type="initial_response",
            cold=True,
            response_time_ms=200.0,
            deployment_id="deploy-2",
            timestamp=now - timedelta(minutes=15),
        ),
        # Metric type A - Warm
        PerformanceMetric(
            metric_type="initial_response",
            cold=False,
            response_time_ms=50.0,
            deployment_id="deploy-1",
            timestamp=now - timedelta(hours=2),
        ),
        PerformanceMetric(
            metric_type="initial_response",
            cold=False,
            response_time_ms=75.0,
            deployment_id="deploy-1",
            timestamp=now - timedelta(minutes=45),
        ),
        PerformanceMetric(
            metric_type="initial_response",
            cold=False,
            response_time_ms=80.0,
            deployment_id="deploy-2",
            timestamp=now - timedelta(minutes=20),
        ),
        # Metric type B - Cold
        PerformanceMetric(
            metric_type="shell_render",
            cold=True,
            response_time_ms=300.0,
            deployment_id="deploy-1",
            timestamp=now - timedelta(hours=3),
        ),
        PerformanceMetric(
            metric_type="shell_render",
            cold=True,
            response_time_ms=350.0,
            deployment_id="deploy-2",
            timestamp=now - timedelta(minutes=10),
        ),
        # Metric type B - Warm
        PerformanceMetric(
            metric_type="shell_render",
            cold=False,
            response_time_ms=120.0,
            deployment_id="deploy-1",
            timestamp=now - timedelta(hours=4),
        ),
        PerformanceMetric(
            metric_type="shell_render",
            cold=False,
            response_time_ms=140.0,
            deployment_id="deploy-2",
            timestamp=now - timedelta(minutes=5),
        ),
        # Additional metrics to test filtering doesn't affect other results
        PerformanceMetric(
            metric_type="other_metric",
            cold=True,
            response_time_ms=500.0,
            deployment_id="deploy-3",
            timestamp=now - timedelta(days=1),
        ),
        PerformanceMetric(
            metric_type="other_metric",
            cold=False,
            response_time_ms=25.0,
            deployment_id="deploy-3",
            timestamp=now - timedelta(days=2),
        ),
    ]

    db.add_all(metrics)
    await db.commit()
    return metrics


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_total_count(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Test that total count matches the total number of metrics."""
    result = await performance_metric_repository.get_performance_metrics_summary(db)

    by_cold, _ = _summary_parts(result)

    # Should count all metrics
    assert result["count"] == len(sample_performance_metrics)

    # Should have both cold and warm entries
    assert True in by_cold
    assert False in by_cold


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_by_cold_counts(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Test that cold/warm counts are correct for the full dataset."""
    result = await performance_metric_repository.get_performance_metrics_summary(db)

    by_cold, _ = _summary_parts(result)

    # Count cold metrics (should be 6: 3 initial_response + 2 shell_render + 1 other_metric)
    cold_count = by_cold[True]
    assert cold_count == 6

    # Count warm metrics (should be 6: 3 initial_response + 2 shell_render + 1 other_metric)
    warm_count = by_cold[False]
    assert warm_count == 6

    # Total should match sum of cold and warm
    assert result["count"] == cold_count + warm_count


@pytest.mark.asyncio
async def test_get_performance_metrics_summary_by_cold_stats(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Test that cold/warm statistics are calculated correctly."""
    result = await performance_metric_repository.get_performance_metrics_summary(db)

    by_cold, by_cold_stats = _summary_parts(result)

    # Test cold stats: sorted [100, 150, 200, 300, 350, 500]
    cold_stats = by_cold_stats[True]
    assert cold_stats["min"] == 100.0  # Minimum cold response time
    assert cold_stats["max"] == 500.0  # Maximum cold response time
    assert cold_stats["median"] == 250.0  # percentile_cont of 200 and 300
    assert cold_stats["p95"] == 462.5  # 350 interpolated 75% toward 500

    # Test warm stats: sorted [25, 50, 75, 80, 120, 140]
    warm_stats = by_cold_stats[False]
    assert warm_stats["min"] == 25.0  # Minimum warm response time
    assert warm_stats["max"] == 140.0  # Maximum warm response time
    assert warm_stats["median"] == 77.5  # percentile_cont of 75 and 80
    assert warm_stats["p95"] == 135.0  # 120 interpolated 75% toward 140


@pytest.mark.asyncio
async def test_filter_by_metric_type(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Test filtering by metric type returns correct counts and stats."""
    result = await performance_metric_repository.get_performance_metrics_summary(
        db, metric_type="initial_response"
    )

    # Should only count initial_response metrics (6 total: 3 cold + 3 warm)
    assert result["count"] == 6

    by_cold, by_cold_stats = _summary_parts(result)

    assert by_cold[True] == 3  # cold initial_response
    assert by_cold[False] == 3  # warm initial_response

    # Check stats are correct for initial_response only
    cold_stats = by_cold_stats[True]
    assert cold_stats["min"] == 100.0
    assert cold_stats["max"] == 200.0
    assert cold_stats["median"] == 150.0
    assert cold_stats["p95"] == 195.0  # 150 interpolated 90% toward 200

    warm_stats = by_cold_stats[False]
    assert warm_stats["min"] == 50.0
    assert warm_stats["max"] == 80.0
    assert warm_stats["median"] == 75.0
    assert warm_stats["p95"] == 79.5  # 75 interpolated 90% toward 80


@pytest.mark.asyncio
async def test_filter_by_deployment_id(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Test filtering by deployment ID returns correct counts and stats."""
    result = await performance_metric_repository.get_performance_metrics_summary(
        db, deployment_id="deploy-1"
    )

    by_cold, _ = _summary_parts(result)

    # Should only count deploy-1 metrics (6 total: 4 initial_response + 2 shell_render)
    assert result["count"] == 6

    # Cold: 2 initial_response + 1 shell_render = 3
    # Warm: 2 initial_response + 1 shell_render = 3
    assert by_cold[True] == 3
    assert by_cold[False] == 3


@pytest.mark.asyncio
async def test_filter_by_metric_type_and_deployment_id(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Test filtering by both metric type and deployment ID."""
    result = await performance_metric_repository.get_performance_metrics_summary(
        db, metric_type="initial_response", deployment_id="deploy-1"
    )

    # Should only count initial_response + deploy-1 (4 total: 2 cold + 2 warm)
    assert result["count"] == 4

    by_cold, by_cold_stats = _summary_parts(result)

    assert by_cold[True] == 2
    assert by_cold[False] == 2

    # Check stats are correct for the two cold and two warm rows
    cold_stats = by_cold_stats[True]
    assert cold_stats["min"] == 100.0
    assert cold_stats["max"] == 150.0
    assert cold_stats["median"] == 125.0
    assert cold_stats["p95"] == 147.5  # 100 interpolated 95% toward 150

    warm_stats = by_cold_stats[False]
    assert warm_stats["min"] == 50.0
    assert warm_stats["max"] == 75.0
    assert warm_stats["median"] == 62.5
    assert warm_stats["p95"] == 73.75  # 50 interpolated 95% toward 75


@pytest.mark.asyncio
async def test_filter_by_timestamp_range(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Test filtering by timestamp range."""
    now = datetime.now(UTC)
    start_time = now - timedelta(hours=1)  # Last hour
    end_time = now  # Now

    result = await performance_metric_repository.get_performance_metrics_summary(
        db, start_time=start_time, end_time=end_time
    )

    # Should only count metrics from the last hour
    # Based on our fixture, this should be 6 metrics
    assert result["count"] == 6


@pytest.mark.asyncio
async def test_filter_to_single_row_isolation(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Test that filtering to one specific row returns count 1 without multiplication.

    This is the critical test for the Cartesian product bug fix.
    """
    # Find a specific metric to filter to
    specific_metric = sample_performance_metrics[0]

    result = await performance_metric_repository.get_performance_metrics_summary(
        db,
        metric_type=specific_metric.metric_type,
        deployment_id=specific_metric.deployment_id,
        cold=specific_metric.cold,
        start_time=specific_metric.timestamp,
        end_time=specific_metric.timestamp,
    )

    # Should return exactly 1 for this specific filter
    assert result["count"] == 1

    by_cold, by_cold_stats = _summary_parts(result)

    assert by_cold[specific_metric.cold] == 1
    assert len(by_cold_stats) == 1
    assert specific_metric.cold in by_cold_stats

    # The single metric's stats should match exactly
    stats = by_cold_stats[specific_metric.cold]
    assert stats["min"] == specific_metric.response_time_ms
    assert stats["max"] == specific_metric.response_time_ms
    assert stats["median"] == specific_metric.response_time_ms
    assert stats["p95"] == specific_metric.response_time_ms


@pytest.mark.asyncio
async def test_empty_filter_results(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Test that empty filter results return appropriate empty structure."""
    result = await performance_metric_repository.get_performance_metrics_summary(
        db, metric_type="nonexistent_metric"
    )

    # Should return 0 count
    assert result["count"] == 0

    # Should have empty by_cold and by_cold_stats dicts
    by_cold, by_cold_stats = _summary_parts(result)
    assert by_cold == {}
    assert by_cold_stats == {}


@pytest.mark.asyncio
async def test_service_contract_preservation(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Test that service layer preserves existing API contract."""
    # Test get_metrics_summary
    summary = await performance_metric_service.get_metrics_summary(db)
    assert "count" in summary
    assert "by_cold" in summary
    assert "by_cold_stats" in summary

    # Test get_cold_warm_comparison
    comparison = await performance_metric_service.get_cold_warm_comparison(db)
    assert "cold" in comparison
    assert "warm" in comparison
    assert "total" in comparison

    # Verify data integrity
    summary_total = cast(int, summary["count"])
    comparison_total = cast(int, comparison["total"])
    cold = cast(dict[str, object], comparison["cold"])
    warm = cast(dict[str, object], comparison["warm"])
    assert summary_total == comparison_total
    assert cast(int, cold["count"]) + cast(int, warm["count"]) == comparison_total


@pytest.mark.asyncio
async def test_sql_no_cartesian_product_evidence(db) -> None:
    """Prove both aggregate statements read one filtered table source.

    The regression shipped ``FROM (subquery), performance_metrics``. This test
    asserts the structural evidence (single non-derived FROM target, single
    ``FROM`` keyword, no join), the planner evidence (no repeated source alias
    and no nested loop crossing two sources), and the functional result for a
    filter that matches exactly one row.
    """
    now = datetime.now(UTC)
    metric = PerformanceMetric(
        metric_type="test_metric",
        cold=True,
        response_time_ms=100.0,
        deployment_id="test-deploy",
        timestamp=now,
    )
    db.add(metric)
    await db.commit()

    with _captured_statements(db) as captured:
        result = await performance_metric_repository.get_performance_metrics_summary(
            db,
            metric_type="test_metric",
            deployment_id="test-deploy",
            cold=True,
        )

    # One count statement and one percentile statement, nothing else.
    assert len(captured) == 2

    for statement in captured:
        sources = list(statement.get_final_froms())
        assert len(sources) == 1, f"expected one FROM source, got {sources}"
        assert isinstance(sources[0], Table)
        assert sources[0].name == "performance_metrics"

        sql = str(statement.compile(dialect=postgresql.dialect(paramstyle="numeric")))
        assert sql.upper().count("FROM ") == 1, sql
        assert "JOIN" not in sql.upper(), sql
        assert "AS ANON_" not in sql.upper(), sql

        plan = await _explain(db, statement)
        # PostgreSQL only aliases a repeated source ("performance_metrics_1") and
        # only crosses two sources through a nested loop, so either marker proves a
        # second table joined the aggregate.
        assert plan.upper().count("ON PERFORMANCE_METRICS") >= 1, plan
        assert "PERFORMANCE_METRICS_1" not in plan.upper(), plan
        assert "NESTED LOOP" not in plan.upper(), plan

    # Verify the results are correct for our single record
    assert result["count"] == 1

    by_cold, by_cold_stats = _summary_parts(result)

    assert by_cold[True] == 1
    single_stats = by_cold_stats[True]
    assert single_stats["min"] == 100.0
    assert single_stats["max"] == 100.0
    assert single_stats["median"] == 100.0
    assert single_stats["p95"] == 100.0


@pytest.mark.asyncio
async def test_unrelated_rows_do_not_change_filtered_summary(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Adding unrelated rows cannot change an already-filtered summary.

    Under the Cartesian product every summary scaled with the total table size,
    so a narrow filter returned ``matching_rows * total_rows``. This asserts the
    filtered summary is stable while the table grows well past the match.
    """
    filters = {
        "metric_type": "initial_response",
        "deployment_id": "deploy-2",
        "start_time": datetime.now(UTC) - timedelta(days=2),
        "end_time": datetime.now(UTC),
    }

    before = await performance_metric_repository.get_performance_metrics_summary(
        db, **filters
    )

    now = datetime.now(UTC)
    noise = [
        PerformanceMetric(
            metric_type=f"noise_metric_{index}",
            cold=index % 2 == 0,
            response_time_ms=float(900 + index),
            deployment_id="deploy-noise",
            timestamp=now - timedelta(minutes=index),
        )
        for index in range(25)
    ]
    db.add_all(noise)
    await db.commit()

    after = await performance_metric_repository.get_performance_metrics_summary(
        db, **filters
    )

    assert after == before

    table_total = await performance_metric_repository.get_performance_metrics_summary(db)
    assert cast(int, table_total["count"]) > cast(int, before["count"])

    by_cold, by_cold_stats = _summary_parts(after)
    # The fixture has exactly two deploy-2 initial_response rows: 200.0 cold and
    # 80.0 warm.
    assert sum(by_cold.values()) == cast(int, before["count"]) == 2
    assert by_cold[True] == 1
    assert by_cold[False] == 1
    assert by_cold_stats[True]["min"] == 200.0
    assert by_cold_stats[True]["max"] == 200.0
    assert by_cold_stats[False]["min"] == 80.0
    assert by_cold_stats[False]["max"] == 80.0


@pytest.mark.asyncio
async def test_combined_filters_boundary_conditions(
    db, sample_performance_metrics: list[PerformanceMetric]
) -> None:
    """Test various combinations of filters and boundary conditions."""
    now = datetime.now(UTC)

    # Test with only start_time (no end_time)
    result = await performance_metric_repository.get_performance_metrics_summary(
        db, start_time=now - timedelta(hours=1)
    )
    assert cast(int, result["count"]) > 0  # Should have some recent metrics

    # Test with only end_time (no start_time)
    result = await performance_metric_repository.get_performance_metrics_summary(
        db, end_time=now
    )
    assert cast(int, result["count"]) > 0  # Should have all metrics

    # Test with cold filter only
    result = await performance_metric_repository.get_performance_metrics_summary(
        db, cold=True
    )
    assert result["count"] == 6  # Should have 6 cold metrics

    # Test with warm filter only
    result = await performance_metric_repository.get_performance_metrics_summary(
        db, cold=False
    )
    assert result["count"] == 6  # Should have 6 warm metrics