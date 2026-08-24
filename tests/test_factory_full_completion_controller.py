"""Regression coverage for full-fleet completion drain selection."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "scripts"
    / "factory_full_completion_controller.py"
)
SPEC = importlib.util.spec_from_file_location("factory_full_completion_controller", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
full = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = full
SPEC.loader.exec_module(full)


def test_full_fleet_selector_removes_normal_backlog_ceiling():
    controller = full.load_controller()
    full.configure_work_conserving_selection(controller)

    workers = [str(worker) for worker in range(6, 26)]
    selected = controller.select_completion_workers(
        workers,
        review_backlog=35,
        now_epoch=1,
    )

    assert selected == sorted(
        workers,
        key=lambda worker: (
            not controller.review_capacity_worker(worker, review_backlog=35),
            int(worker),
        ),
    )


def test_transient_cooldowns_are_fallback_capacity_but_model_missing_is_not():
    controller = full.load_controller()
    full.configure_work_conserving_selection(controller)
    now = controller.parse_time("2026-08-24T17:00:00Z")
    assert now is not None

    workers = ["6", "7", "8", "9", "10", "11"]
    health = {
        "6": ("failure", now - 60),
        "8": ("RATE LIMITED", now - 60),
        "10": ("MODEL MISSING", now - 60),
    }

    selected = controller.select_completion_workers(
        workers,
        review_backlog=35,
        owned_workers={"7"},
        health=health,
        now_epoch=now,
    )

    assert "7" not in selected
    assert "10" not in selected
    assert set(selected) == {"6", "8", "9", "11"}
    # Healthy workers are consumed before transiently cooling fallback capacity.
    assert selected.index("9") < selected.index("6")
    assert selected.index("11") < selected.index("8")
