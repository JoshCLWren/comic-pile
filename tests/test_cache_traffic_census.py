"""Pin the September 2026 cache-command census to the decision rule."""

from __future__ import annotations

import json
from pathlib import Path

from app.cache_metrics import CACHE_FLOW_COMMAND_CEILINGS, CONSERVATIVE_MONTHLY_COMMAND_BUDGET
from app.cache_provider_decision import project_monthly_cache_commands

CENSUS_PATH = Path("docs/CACHE_TRAFFIC_CENSUS_2026-09.json")
LATENCY_PATH = Path("docs/CACHE_LOOKUP_LATENCY_2026-08.json")


def _load_census() -> dict[str, object]:
    """Load the committed Vercel runtime-log census document."""
    return json.loads(CENSUS_PATH.read_text(encoding="utf-8"))


def test_census_monthly_counts_use_documented_flows_only() -> None:
    """The census cannot invent flows beyond CACHE_FLOW_COMMAND_CEILINGS."""
    census = _load_census()
    monthly = census["monthly_flow_counts"]
    assert isinstance(monthly, dict)
    assert set(monthly) == set(CACHE_FLOW_COMMAND_CEILINGS)
    assert all(isinstance(count, int) and count >= 0 for count in monthly.values())


def test_census_projection_stays_under_budget_with_headroom() -> None:
    """The conservative scaled census is far below the 350,000-command gate."""
    census = _load_census()
    monthly = census["monthly_flow_counts"]
    assert isinstance(monthly, dict)
    projection = project_monthly_cache_commands(monthly)

    assert projection.within_budget is True
    assert projection.total_commands < 10_000
    assert projection.budget_commands == CONSERVATIVE_MONTHLY_COMMAND_BUDGET


def test_pathological_all_requests_as_rolls_still_under_budget() -> None:
    """Even mapping every observed request to the 5-command roll ceiling is a GO."""
    census = _load_census()
    bound = census["pathological_upper_bound"]
    assert isinstance(bound, dict)
    commands = bound["commands_if_all_rolls"]
    assert isinstance(commands, int)
    assert commands < CONSERVATIVE_MONTHLY_COMMAND_BUDGET
    assert project_monthly_cache_commands({"roll": 70_000}).within_budget is False


def test_monthly_counts_are_scaled_from_seven_day_window() -> None:
    """Bootstrap and queue_load counts keep the documented 4x * 30/7 scale."""
    census = _load_census()
    observed = census["observed_7d_flow_counts"]
    monthly = census["monthly_flow_counts"]
    scale = census["monthly_scale"]
    multiplier = census["uncertainty_multiplier"]
    assert isinstance(observed, dict)
    assert isinstance(monthly, dict)
    assert isinstance(scale, float)
    assert isinstance(multiplier, int)

    bootstrap = observed["bootstrap"]
    queue_load = observed["queue_load"]
    assert isinstance(bootstrap, int)
    assert isinstance(queue_load, int)
    expected_bootstrap = round(bootstrap * scale * multiplier)
    expected_queue = round(queue_load * scale * multiplier)
    assert monthly["bootstrap"] == expected_bootstrap
    assert monthly["queue_load"] == expected_queue


def test_committed_latency_json_has_neon_samples_and_skipped_upstash() -> None:
    """The filled JSON is redacted, has 30 Neon samples, and cannot yet recommend Redis."""
    report = json.loads(LATENCY_PATH.read_text(encoding="utf-8"))
    neon = report["neon_point_select"]["summary"]["elapsed_ms"]
    upstash = report["upstash_rest_get"]

    assert report["measured_from"] == "github-actions:ubuntu-latest"
    assert report["iterations"] == 30
    assert neon["p50"] == 143.303
    assert neon["p95"] == 151.812
    assert upstash["summary"] is None
    assert upstash["quota_blocked"] is False
    assert "upstash.io" not in json.dumps(report)
