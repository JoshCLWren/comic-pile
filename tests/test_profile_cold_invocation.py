"""Offline checks for complete cold invocation profile artifacts."""

import json
from pathlib import Path

import pytest

from scripts.profile_cold_invocation import profile_samples, summary


def test_speedscope_sample_count(tmp_path: Path) -> None:
    """Accept actual sampled Speedscope stacks without needing py-spy in CI."""
    path = tmp_path / "cpu.speedscope.json"
    path.write_text(
        json.dumps({
            "$schema": "https://www.speedscope.app/file-format-schema.json",
            "profiles": [
                {"type": "sampled", "samples": [[0, 1], [0, 2]], "weights": [1, 1]},
                {"type": "sampled", "samples": [[0, 1]], "weights": [1]},
            ],
        })
    )
    assert profile_samples(path) == 3


@pytest.mark.parametrize("profiles", [[], None])
def test_reject_missing_stacks(tmp_path: Path, profiles: list | None) -> None:
    path = tmp_path / "bad.speedscope.json"
    path.write_text(json.dumps({"profiles": profiles}))
    with pytest.raises(ValueError, match="usable Speedscope stacks"):
        profile_samples(path)


def test_report_shows_startup_plus_first_request_and_warm_control() -> None:
    result = {
        "run": 1,
        "startup_cpu_ms": 458.0,
        "first_request_cpu_ms": 327.0,
        "full_cold_cpu_ms": 785.0,
        "first_request_wall_ms": 45.2,
        "warm_cpu_per_request_ms": 10.2,
        "profile_stack_records": 215,
        "speedscope": ".profile-local/cold-1.speedscope.json",
    }
    output = summary([result])
    assert "| 1 | 458.0 ms | 327.0 ms | 785.0 ms | 45.2 ms | 10.2 ms | 215 |" in output
    assert ".profile-local/cold-1.speedscope.json" in output
    assert "NOT Vercel billing" in output
