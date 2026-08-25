"""Regression coverage for the generated factory status dashboard."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "scripts"
    / "generate_factory_status_dashboard.py"
)
SPEC = importlib.util.spec_from_file_location("generate_factory_status_dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dashboard
SPEC.loader.exec_module(dashboard)


def test_dashboard_surfaces_operational_state_in_one_page():
    """Render the core factory metrics, throughput, and allocator state together."""
    rendered = dashboard.render_dashboard(
        {
            "generated_at": "2026-08-24T23:50:00Z",
            "open_prs": 66,
            "open_issues": 120,
            "completion_demand": 30,
            "production_demand": 10,
            "completion_share": 0.75,
            "completion_target": 15,
            "configured_workers": 46,
            "busy_workers": 20,
            "idle_workers": 20,
            "cooling_workers": 4,
            "unavailable_workers": 2,
            "pipeline": {
                "review": 8,
                "changes_requested": 21,
                "ci": 4,
                "ready": 1,
                "unowned": 3,
                "conflict": 2,
            },
            "throughput": {
                "opened_hour": 4,
                "merged_hour": 12,
                "net_hour": -8,
                "opened_day": 30,
                "merged_day": 48,
                "net_day": -18,
            },
            "funnel": {
                "completion target": "15",
                "workers selected": "15",
                "pr claims succeeded": "14",
                "updated": "2026-08-24T23:49:00Z",
            },
        }
    )

    assert "ComicPile Factory" in rendered
    assert "75%" in rendered
    assert "Changes requested" in rendered
    assert "Net PR change" in rendered
    assert "-8" in rendered
    assert "target 15 · selected 15 · claims 14" in rendered
    assert "refreshes every 5 min" in rendered
