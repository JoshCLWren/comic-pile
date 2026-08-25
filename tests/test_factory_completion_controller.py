"""Regression coverage for completion-drain scheduling and worker health."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "factory_completion_controller.py"
SPEC = importlib.util.spec_from_file_location("factory_completion_controller", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)


def test_completion_batch_size_scales_with_backlog():
    assert controller.completion_batch_size(14) == 0
    assert controller.completion_batch_size(15) == 8
    assert controller.completion_batch_size(49) == 8
    assert controller.completion_batch_size(50) == 12
    assert controller.completion_batch_size(80) == 12


def test_health_cooldowns_distinguish_capacity_failures():
    assert controller.cooldown_seconds("success") == 0
    assert controller.cooldown_seconds("failure") == 15 * 60
    assert controller.cooldown_seconds("RATE LIMITED") == 30 * 60
    assert controller.cooldown_seconds("MODEL MISSING") == 6 * 60 * 60


def test_latest_worker_health_uses_newest_heartbeat():
    comments = [
        {
            "body": "Worker: opencode-free-model-factory-41\nOutcome: RATE LIMITED\nUpdated: 2026-08-24T11:00:00Z"
        },
        {
            "body": "Worker: opencode-free-model-factory-41\nOutcome: success\nUpdated: 2026-08-24T11:20:00Z"
        },
    ]
    health = controller.latest_worker_health(comments)
    assert health["41"][0] == "success"


def test_completion_selection_skips_owned_and_cooling_workers():
    now = controller.parse_time("2026-08-24T12:00:00Z")
    assert now is not None
    workers = [str(worker) for worker in range(6, 30)]
    health = {
        "6": ("failure", now - 60),
        "10": ("RATE LIMITED", now - 60),
        "14": ("MODEL MISSING", now - 60),
    }
    selected = controller.select_completion_workers(
        workers,
        review_backlog=80,
        owned_workers={"7", "8"},
        health=health,
        now_epoch=now,
    )
    assert len(selected) == 12
    assert not {"6", "7", "8", "10", "14"} & set(selected)


def test_completion_selection_prefers_review_capacity_at_high_backlog():
    workers = ["9", "10", "19", "20", "29", "30", "39", "40", "49", "50", "59", "60", "69", "70"]
    selected = controller.select_completion_workers(
        workers,
        review_backlog=80,
        now_epoch=1,
    )
    review_first = [
        worker
        for worker in selected
        if controller.review_capacity_worker(worker, review_backlog=80)
    ]
    assert selected[: len(review_first)] == review_first
    assert len(selected) == 12
