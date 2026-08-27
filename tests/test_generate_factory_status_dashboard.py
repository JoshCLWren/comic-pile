"""Regression coverage for the generated factory status dashboard."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

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
            "executable_capacity": 22,
            "executable_slot_capacity": 22,
            "healthy_slots": 18,
            "degraded_slots": 4,
            "cooling_slots": 3,
            "unavailable_slots": 2,
            "executable_candidate_count": 6,
            "healthy_candidates": 5,
            "degraded_candidates": 1,
            "cooling_candidates": 2,
            "unavailable_candidates": 1,
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
    assert "Executable capacity now" in rendered
    assert "Executable slots" in rendered
    assert "Executable provider/models" in rendered
    assert "22" in rendered
    assert "6" in rendered
    assert "refreshes every 5 min" in rendered


def test_collect_snapshot_unpacks_demand_and_authoritative_capacity(
    monkeypatch: pytest.MonkeyPatch,
):
    """Use the allocator's demand/capacity tuple without recomputing health."""
    work = SimpleNamespace(list_issues=lambda: [], list_prs=lambda: [])
    completion = SimpleNamespace(
        load_controller=lambda: work,
        load_manifest_workers=lambda _path: ["39", "40"],
        owned_worker_ids=lambda _items: {"39"},
    )
    demand = SimpleNamespace(
        completion=7,
        production=3,
        completion_share=0.7,
        idle_workers=1,
    )
    capacity = {
        "executable_capacity": 1,
        "executable_slot_capacity": 1,
        "slot_health_counts": {
            "healthy": 1,
            "degraded": 0,
            "cooling": 1,
            "unavailable": 0,
        },
        "executable_candidate_count": 1,
        "candidate_health_counts": {
            "healthy": 1,
            "degraded": 0,
            "cooling": 0,
            "unavailable": 0,
        },
    }
    full = SimpleNamespace(
        current_demand=lambda _controller: (demand, capacity),
        completion_worker_target=lambda _demand: 1,
    )

    def fake_load_module(_name: str, path: Path):
        return full if path.name == "factory_full_completion_controller.py" else completion

    monkeypatch.setattr(dashboard, "load_module", fake_load_module)
    monkeypatch.setattr(dashboard, "github_search_total", lambda *_args: 0)
    monkeypatch.setattr(dashboard, "latest_completion_funnel", lambda _controller: {})

    snapshot = dashboard.collect_snapshot()

    assert snapshot["completion_demand"] == 7
    assert snapshot["production_demand"] == 3
    assert snapshot["executable_capacity"] == 1
    assert snapshot["executable_slot_capacity"] == 1
    assert snapshot["healthy_slots"] == 1
    assert snapshot["cooling_slots"] == 1
    assert snapshot["executable_candidate_count"] == 1
    assert snapshot["healthy_candidates"] == 1
    assert snapshot["cooling_candidates"] == 0
