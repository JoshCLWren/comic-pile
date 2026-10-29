"""Deterministic checks for cold Roll CPU paired A/B reporting."""

from __future__ import annotations

import pytest

from scripts.compare_cold_router_cpu import pair_order, summarize


def test_pair_order_alternates_control_first() -> None:
    """Avoid comparing two separately timed/cached checkout directories."""
    assert pair_order(1) == ("baseline", "fixed")
    assert pair_order(2) == ("fixed", "baseline")
    assert pair_order(3) == ("baseline", "fixed")


def _row(pair: int, variant: str, total: float, first: float) -> dict:
    """Build a representative uninstrumented CPU sample."""
    return {
        "pair": pair,
        "variant": variant,
        "startup_cpu_ms": total - first,
        "first_request_cpu_ms": first,
        "full_cold_cpu_ms": total,
        "first_request_wall_ms": first * 1.2,
        "warm_cpu_per_request_ms": 8.5,
    }


def test_paired_cpu_summary_uses_median_of_pairwise_savings() -> None:
    """Preserve per-pair deltas rather than inferring savings from profiled CPU."""
    rows = [
        _row(1, "baseline", 740, 295),
        _row(1, "fixed", 680, 231),
        _row(2, "fixed", 705, 235),
        _row(2, "baseline", 760, 300),
        _row(3, "baseline", 745, 297),
        _row(3, "fixed", 720, 230),
    ]
    report = summarize(rows)
    assert "| 1 | 740.00 ms | 680.00 ms | +60.00 ms | 295.00 ms | 231.00 ms |" in report
    assert "| 2 | 760.00 ms | 705.00 ms | +55.00 ms | 300.00 ms | 235.00 ms |" in report
    assert "| 3 | 745.00 ms | 720.00 ms | +25.00 ms | 297.00 ms | 230.00 ms |" in report
    assert "| full_cold_cpu_ms | 745.00 | 705.00 | +55.00 |" in report
    assert "NOT Vercel billing" in report


def test_paired_summary_rejects_missing_variant() -> None:
    """Incomplete comparisons must never be reported as improvements."""
    with pytest.raises(ValueError, match="same completed pairs"):
        summarize([_row(1, "baseline", 740, 295)])
