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
    assert controller.cooldown_seconds("model_unavailable") == 6 * 60 * 60
    assert controller.cooldown_seconds("provider_unavailable") == 30 * 60
    assert controller.cooldown_seconds("model_interruption") == 15 * 60
    assert controller.cooldown_seconds("worker_environment_failure") == 15 * 60
    assert controller.cooldown_seconds("no_change") == 0
    assert controller.cooldown_seconds("work_failure") == 0
    assert controller.cooldown_seconds("policy_blocked") == 0


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


def test_classified_attempt_outcome_survives_newer_liveness_heartbeat():
    comments = [
        {
            "body": (
                "Worker: opencode-free-model-factory-41\n"
                "Outcome: MODEL MISSING\n"
                "Attempt outcome: model_unavailable\n"
                "Updated: 2026-08-24T11:00:00Z"
            )
        },
        {
            "body": (
                "Worker: opencode-free-model-factory-41\n"
                "Outcome: running\n"
                "Updated: 2026-08-24T11:20:00Z"
            )
        },
    ]
    health = controller.latest_worker_health(comments)
    assert health["41"][0] == "model_unavailable"


def test_newest_classified_attempt_replaces_older_attempt():
    comments = [
        {
            "body": (
                "Worker: opencode-free-model-factory-41\n"
                "Attempt outcome: provider_unavailable\n"
                "Updated: 2026-08-24T11:00:00Z"
            )
        },
        {
            "body": (
                "Worker: opencode-free-model-factory-41\n"
                "Attempt outcome: success\n"
                "Updated: 2026-08-24T11:20:00Z"
            )
        },
    ]
    health = controller.latest_worker_health(comments)
    assert health["41"][0] == "success"


def test_completion_selection_skips_owned_and_cooling_workers():
    now = controller.parse_time("2026-08-24T12:00:00Z")
    assert now is not None
    workers = [str(worker) for worker in range(6, 30)]
    health = {
        **dict.fromkeys(workers, ("success", now - 60)),
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
    health = dict.fromkeys(workers, ("success", 0))
    selected = controller.select_completion_workers(
        workers,
        review_backlog=80,
        health=health,
        now_epoch=1,
    )
    review_first = [
        worker
        for worker in selected
        if controller.review_capacity_worker(worker, review_backlog=80)
    ]
    assert selected[: len(review_first)] == review_first
    assert len(selected) == 12


def test_health_state_fails_closed_without_runtime_evidence():
    assert controller.worker_health_state("41", {}, now_epoch=100) == "unknown"
    assert not controller.worker_is_executable("41", {}, now_epoch=100)


def test_health_state_distinguishes_unavailable_cooling_and_recovery():
    now = controller.parse_time("2026-08-24T17:00:00Z")
    assert now is not None
    assert (
        controller.worker_health_state(
            "41",
            {"41": ("model_unavailable", now - 86400)},
            now_epoch=now,
        )
        == "unavailable"
    )
    assert (
        controller.worker_health_state(
            "41",
            {"41": ("provider_unavailable", now - 60)},
            now_epoch=now,
        )
        == "cooling"
    )
    assert (
        controller.worker_health_state(
            "41",
            {"41": ("provider_unavailable", now - 3600)},
            now_epoch=now,
        )
        == "degraded"
    )
    assert (
        controller.worker_health_state(
            "41",
            {"41": ("success", now)},
            now_epoch=now,
        )
        == "healthy"
    )


def test_capacity_report_names_only_executable_candidates():
    candidates = [
        {"worker": "41", "provider": "opencode-free", "model": "mimo"},
        {"worker": "42", "provider": "nvidia", "model": "retired"},
        {"worker": "43", "provider": "openrouter-free", "model": "unknown"},
    ]
    health = {
        "41": ("success", 100),
        "42": ("model_unavailable", 100),
    }
    report = controller.capacity_report(candidates, health, now_epoch=100)
    assert report["executable_capacity"] == 1
    assert report["health_counts"] == {
        "unknown": 1,
        "healthy": 1,
        "degraded": 0,
        "cooling": 0,
        "unavailable": 1,
    }
    assert report["executable_candidates"] == [
        {
            "worker": "41",
            "provider": "opencode-free",
            "model": "mimo",
            "health": "healthy",
        }
    ]
