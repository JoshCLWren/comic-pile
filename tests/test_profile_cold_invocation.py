"""Offline checks for the macOS-compatible cold-invocation CPU profiler."""

from __future__ import annotations

import cProfile
from pathlib import Path
import pstats
import time

import pytest

from scripts.profile_cold_invocation import profile_function_count, summary
from scripts.profile_cold_server import save_profile


def _workload() -> int:
    """Run an inexpensive but identifiable Python function for profiling."""
    return sum(i * i for i in range(200))


def test_cpu_profile_writes_call_graph_and_hot_function_report(tmp_path: Path) -> None:
    """Stdlib profiling writes usable pstats with both CPU attribution tables."""
    output = tmp_path / "cold-1.pstats"
    profile = cProfile.Profile(timer=time.process_time)
    profile.enable()
    assert _workload() > 0
    profile.disable()

    stats_path, top_path = save_profile(profile, output)
    assert stats_path == output
    assert stats_path.is_file()
    assert top_path.is_file()
    assert "Top 50 functions by SELF CPU" in top_path.read_text()
    assert "Top 50 functions by CUMULATIVE CPU" in top_path.read_text()
    assert "_workload" in top_path.read_text()
    assert profile_function_count(output) > 0
    assert pstats.Stats(str(output)).total_calls > 0


def test_invalid_cpu_profile_is_rejected(tmp_path: Path) -> None:
    """Missing stats files are not mistaken for successful instrumentation."""
    with pytest.raises(OSError):
        profile_function_count(tmp_path / "missing.pstats")


def test_report_separates_unprofiled_cpu_from_instrumented_stacks() -> None:
    """Never label cProfile-inflated CPU as the real cold-start baseline."""
    result = {
        "run": 1,
        "startup_cpu_ms": 458.0,
        "first_request_cpu_ms": 327.0,
        "full_cold_cpu_ms": 785.0,
        "first_request_wall_ms": 45.2,
        "warm_cpu_per_request_ms": 10.2,
        "profile_functions": 215,
        "profile_path": ".profile-local/cold-1.pstats",
        "profile_top_path": ".profile-local/cold-1.top.txt",
    }
    output = summary([result])
    assert "| 1 | 458.0 ms | 327.0 ms | 785.0 ms | 45.2 ms | 10.2 ms | 215 |" in output
    assert ".profile-local/cold-1.pstats" in output
    assert ".profile-local/cold-1.top.txt" in output
    assert "NOT Vercel billing" in output
    assert "unprofiled processes" in output
