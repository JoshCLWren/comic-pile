"""Trusted event projection and heartbeat diagnostics."""
from __future__ import annotations
import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
runtime = importlib.import_module("factory_runtime_view")
heartbeat = importlib.import_module("factory_heartbeat_health")

def test_events_do_not_infer_success_from_running_status():
    view = runtime.project_events([
        {"event_type": "worker_started", "created_at": "2026-11-16T00:00:00Z",
         "detail": {"worker": "43", "run_id": "10", "status": "running"}},
        {"event_type": "worker_heartbeat", "created_at": "2026-11-16T00:05:00Z",
         "detail": {"worker": "43", "run_id": "10", "status": "finished"}},
        {"event_type": "worker_failed", "created_at": "2026-11-16T00:06:00Z",
         "detail": {"worker": "43", "run_id": "10", "outcome_class": "provider_quota",
                    "source": "requesty", "model": "x"}},
    ])
    assert view["heartbeats"]["43"]["outcome"] == "finished"
    assert view["attempts"]["43"]["attempt outcome"] == "provider_quota"

def test_stale_worker_is_visible_without_retry_authority():
    view = {"heartbeats": {"43": {"updated": "2026-11-15T23:00:00Z",
                                  "run": "10", "outcome": "finished"}},
            "attempts": {"43": {"attempt outcome": "provider_quota",
                                 "updated": "2026-11-16T00:00:00Z"}}}
    report = heartbeat.heartbeat_health_from_view(
        view, {"expected_workers": [43]}, now=datetime(2026, 11, 16, 1, tzinfo=UTC),
    )
    workers = report["workers"]
    assert isinstance(workers, list)
    assert workers[0]["freshness"] == "stale"
    assert workers[0]["runtime_status"] == "quota-limited"
    assert report["newest_active_age_seconds"] == 7200
    recovery = report["recovery_policy"]
    assert isinstance(recovery, str)
    assert "no per-worker stale retries" in recovery
