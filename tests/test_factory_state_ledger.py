"""Trusted-only Neon lifecycle and transactional lease regressions (no network)."""
from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".github/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("factory_state_ledger_test", SCRIPTS / "factory_state_ledger.py")
assert SPEC is not None and SPEC.loader is not None
ledger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ledger)


def test_keys_cover_worker_and_entire_target_group():
    assert ledger._keys("owner/repo", "42", [501, 499, 501]) == [
        "factory-lease-v1:owner/repo:worker:42",
        "factory-lease-v1:owner/repo:target:499",
        "factory-lease-v1:owner/repo:target:501",
    ]


def test_unconfigured_controller_retains_legacy_github_claim_behavior(monkeypatch):
    monkeypatch.delenv("FACTORY_STATE_DSN_FILE", raising=False)
    assert ledger.acquire_lease("owner/repo", "42", [5001]) == ""
    assert ledger.release_lease("owner/repo", "42", "", "rollback") is False


@pytest.mark.parametrize("worker,numbers,ttl", [
    ("factory:42", [5001], 900),
    ("42", [], 900),
    ("42", [0], 900),
    ("42", [5001], 30),
])
def test_invalid_lease_requests_rejected(worker, numbers, ttl):
    with pytest.raises(ValueError):
        ledger.acquire_lease("owner/repo", worker, numbers, ttl)


def test_claim_conflict_propagates_without_github_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "dsn"))
    monkeypatch.setattr(ledger, "_acquire", lambda *args: "unused")
    monkeypatch.setattr(ledger.asyncio, "run", lambda coroutine: None)
    assert ledger.acquire_lease("owner/repo", "42", [5001]) is None


def test_db_error_is_not_silenced_after_configured_claim(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_STATE_DSN_FILE", str(tmp_path / "dsn"))
    def fail(coroutine):
        coroutine.close()
        raise ConnectionError("Neon down")
    monkeypatch.setattr(ledger.asyncio, "run", fail)
    with pytest.raises(ConnectionError):
        ledger.acquire_lease("owner/repo", "42", [5001])


def test_trusted_recent_running_heartbeat_is_recorded_once(monkeypatch):
    import importlib
    factory_work_policy = importlib.import_module("factory_work_policy")
    monkeypatch.setattr(factory_work_policy, "comment_is_trusted", lambda c: c.get("trusted") is True)
    found = []
    monkeypatch.setattr(ledger, "record_events", lambda repo, entries: found.extend(entries) or len(entries))
    now = datetime.now(UTC).isoformat()
    body = "<!-- factory-heartbeat:v1 worker=opencode-free-model-factory-42 -->\nOutcome: running\nRun: 43123\n"
    assert ledger.record_heartbeat_comments("owner/repo", [
        {"id": 15, "updated_at": now, "body": body, "trusted": True},
        {"id": 16, "updated_at": now, "body": body, "trusted": False},
        {"id": 17, "updated_at": (datetime.now(UTC)-timedelta(days=1)).isoformat(),
         "body": body, "trusted": True},
    ]) == 1
    assert found[0]["event_type"] == "worker_started"
    assert found[0]["worker"] == "42"
    assert found[0]["run_id"] == "43123"


def test_terminal_classification_is_idempotency_keyed_by_run(monkeypatch):
    records = []
    monkeypatch.setattr(ledger, "record_events", lambda _, events: records.extend(events) or len(events))
    assert ledger.record_runtime_outcome("owner/repo", "12345", {
        "worker": "42", "outcome_class": "provider_failure",
        "persisted_work": False,
    }) == 1
    assert records[0]["event_type"] == "worker_failed"
    assert records[0]["event_id"] == "runtime:12345"
    records.clear()
    ledger.record_runtime_outcome("owner/repo", "12346", {
        "worker": "42", "outcome_class": "success",
        "persisted_work": True,
    })
    assert records[0]["event_type"] == "worker_completed"
    assert records[0]["persisted_work"] is True


def test_only_trusted_collectors_and_observer_use_ledger():
    root = Path(__file__).resolve().parents[1]
    controller = (root / ".github/scripts/factory-work-controller.py").read_text()
    collector = (root / ".github/scripts/factory_completion_controller.py").read_text()
    observer = (root / ".github/workflows/fixed-model-runtime-observer.yml").read_text()
    untrusted = (root / ".github/workflows/free-model-factory-run.yml").read_text()
    entry = (root / ".github/workflows/free-model-factory-entry.yml").read_text()
    assert "acquire_lease(REPO, worker, numbers, FIXED_LEASE_TTL_SECONDS)" in controller
    assert "release_lease(REPO, worker, claim_token, 'claim-rollback')" in controller
    assert "record_heartbeat_comments(REPO, changes)" in collector
    assert "Persist classified worker completion in Neon" in observer
    assert "factory-state-cache" not in untrusted
    assert "factory-state-cache" not in entry


def test_trusted_heartbeat_events_extend_current_nonexpired_lease() -> None:
    import inspect

    source = inspect.getsource(ledger._events)
    assert 'entry["event_type"] == "worker_started"' in source
    assert "def renew_verified_workers(" in inspect.getsource(ledger.renew_verified_workers)
    assert "expires_at>now()" in inspect.getsource(ledger._renew_verified)
    assert "AND expires_at>now()" in source
    assert "payload->0->>'claim_id'=$2" in source


def test_completion_dispatch_persists_real_worker_outcomes() -> None:
    root = Path(__file__).resolve().parents[1]
    entry = (root / ".github/workflows/free-model-factory-entry.yml").read_text()
    drain = (root / ".github/workflows/factory-completion-drain.yml").read_text()
    assert '-f source_run_id="$GITHUB_RUN_ID"' in entry
    assert "persist_outcome:" in drain
    assert '.path == ".github/workflows/free-model-factory-entry.yml"' in drain
    assert ".head_repository.full_name == $repo" in drain
    assert "actions/jobs/${job_id}/logs" in drain
    assert "factory_state_ledger.py runtime-outcome" in drain
    assert "factory-state-cache" not in entry
    assert "factory-state-cache" not in (root / ".github/workflows/free-model-factory-run.yml").read_text()


def test_verified_lease_renewal_is_only_called_after_actions_liveness() -> None:
    import inspect

    controller = (Path(__file__).resolve().parents[1] / ".github/scripts/factory-work-controller.py").read_text()
    assert "renew_verified_workers(REPO, [str(worker) for worker in active])" in controller
    assert "prior_claims[worker_id] = worker_claim(REPO, worker_id)" in controller
    assert "release_lease(REPO, worker_id, token, 'stale-lease-reconciled')" in controller
    assert "not target_owned_by(number, f'factory:{worker_id}')" in controller
    assert '"worker_outcome_signal" if status in {"success", "failure"}' in inspect.getsource(
        ledger.record_heartbeat_comments
    )
