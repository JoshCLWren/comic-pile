"""Regressions for bounded recovery and factory incident routing."""

import importlib.util
import io
import json
import sys
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"


@pytest.fixture
def recovery(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the trusted workflow helper and its sibling freeze evaluator."""
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "factory_deploy_recovery", SCRIPTS / "factory_deploy_recovery.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def failed_run() -> dict[str, object]:
    """Return an actual failed deployment with a failed health smoke."""
    return {
        "id": 11,
        "name": "Deploy Production",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "failure",
        "updated_at": "2026-11-08T10:00:00Z",
        "html_url": "https://github.com/example/repo/actions/runs/11",
        "jobs": [
            {
                "name": "Migrate Neon and deploy exact main SHA",
                "conclusion": "failure",
                "steps": [{"name": "Smoke production Rust health", "conclusion": "failure"}],
            }
        ],
    }


def repair() -> dict[str, object]:
    """Return a newly merged deploy repair on main."""
    return {
        "number": 42,
        "baseRefName": "main",
        "mergeCommit": {"oid": "b" * 40},
        "mergedAt": "2026-11-08T11:00:00Z",
        "labels": [{"name": "deploy-fix"}],
    }


def test_repair_is_consumed_by_next_failed_attempt(recovery: ModuleType) -> None:
    """A prior merged fix cannot authorize endless retries after another failure."""
    run = failed_run()
    assert recovery.repair_candidates(run, [repair()]) == [(42, "b" * 40)]
    run["updated_at"] = "2026-11-08T12:00:00Z"
    assert recovery.repair_candidates(run, [repair()]) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("baseRefName", "other"),
        ("mergeCommit", None),
        ("mergedAt", None),
        ("labels", []),
        ("mergeCommit", {"oid": "invalid"}),
    ],
)
def test_unmerged_unlabelled_and_wrong_base_do_not_authorize(
    recovery: ModuleType, field: str, value: object
) -> None:
    """Only a complete merged repair record can grant recovery."""
    pull = repair()
    pull[field] = value
    assert recovery.repair_candidates(failed_run(), [pull]) == []


def test_repair_must_be_in_current_main(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A merged fix on a divergent/reset history cannot grant an attempt."""
    monkeypatch.setattr(recovery, "gh_json", lambda args: [repair()])
    monkeypatch.setattr(
        recovery.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 1)
    )
    assert recovery.merged_repair(failed_run(), "example/repo") is None
    monkeypatch.setattr(
        recovery.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0)
    )
    assert recovery.merged_repair(failed_run(), "example/repo") == 42


def exercise_reconcile(
    recovery: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    run: dict[str, object],
    incidents: list[dict[str, object]],
) -> list[list[str]]:
    """Run reconciliation against captured GitHub operations."""
    calls: list[list[str]] = []

    def api(arguments: list[str]) -> object:
        calls.append(arguments)
        if arguments[:2] == ["api", "--paginate"]:
            return [{"workflow_runs": [run]}]
        if arguments[:2] == ["issue", "list"]:
            return incidents
        return {}

    monkeypatch.setattr(recovery, "gh_json", api)
    recovery.reconcile("example/repo")
    return calls


def test_failure_creates_actionable_factory_incident(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual failure produces an executable, deduplicated repair task."""
    calls = exercise_reconcile(recovery, monkeypatch, failed_run(), [])
    create = calls[-1]
    assert "POST" in create
    assert "repos/example/repo/issues" in create
    assert "labels[]=deploy-fix" in create
    assert "labels[]=factory:unowned" in create
    assert "labels[]=ralph-status:pending" in create
    assert any("Smoke production Rust health" in arg for arg in create)
    assert any("actions/runs/11" in arg for arg in create)


def test_failure_refresh_preserves_live_lease(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Heartbeat changes only incident evidence, leaving labels/ownership intact."""
    incidents = [{"number": 8, "body": recovery.MARKER, "labels": [{"name": "factory:local"}]}]
    calls = exercise_reconcile(recovery, monkeypatch, failed_run(), incidents)
    assert "PATCH" in calls[-1]
    assert "repos/example/repo/issues/8" in calls[-1]
    assert not any("labels" in arg for arg in calls[-1])
    # Identical heartbeats do not spam comments or update issue activity.
    incidents[0]["body"] = recovery.incident_body(failed_run())
    calls = exercise_reconcile(recovery, monkeypatch, failed_run(), incidents)
    assert len(calls) == 2


def test_success_needs_both_real_smokes(recovery: ModuleType) -> None:
    """Neither a green freeze gate nor a partial smoke result proves recovery."""
    run = failed_run()
    run["conclusion"] = "success"
    run["jobs"] = [{"name": recovery.DEPLOY_JOB_NAME, "conclusion": "skipped"}]
    assert not recovery.successful_smokes(run)
    run["jobs"] = [{"name": recovery.DEPLOY_JOB_NAME, "conclusion": "success", "steps": []}]
    assert not recovery.successful_smokes(run)
    run["jobs"] = [
        {
            "name": recovery.DEPLOY_JOB_NAME,
            "conclusion": "success",
            "steps": [{"name": name, "conclusion": "success"} for name in recovery.SMOKES],
        }
    ]
    assert recovery.successful_smokes(run)


def test_green_attempt_closes_only_managed_incidents(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proven recovery closes its own incident, with a verification comment."""
    run = failed_run()
    run["conclusion"] = "success"
    run["jobs"] = [
        {
            "name": recovery.DEPLOY_JOB_NAME,
            "conclusion": "success",
            "steps": [{"name": name, "conclusion": "success"} for name in recovery.SMOKES],
        }
    ]
    calls = exercise_reconcile(
        recovery,
        monkeypatch,
        run,
        [
            {"number": 8, "body": recovery.MARKER},
            {"number": 9, "body": "Unrelated deploy-fix"},
        ],
    )
    assert "repos/example/repo/issues/8/comments" in calls[-2]
    assert "state=closed" in calls[-1]
    assert not any("issues/9" in arg for call in calls for arg in call)


def test_recovery_workflow_uses_trusted_main_and_heartbeat() -> None:
    """Repair reconciliation is activated on failures and already-latched freezes."""
    workflow = (SCRIPTS.parent / "workflows" / "production-deploy-recovery.yml").read_text()
    assert "workflows: [Deploy Production]" in workflow
    assert "cron:" in workflow
    assert "ref: main" in workflow
    assert "secrets." not in workflow
    deploy = (SCRIPTS.parent / "workflows" / "deploy-production.yml").read_text()
    assert "--recover-reviewed-fix" in deploy
    assert "--build-env COMICPILE_BUILD_SHA=" in deploy
    assert ".build.revision == $sha" in deploy


def test_recovered_incident_keeps_active_worker_lease(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful external deploy does not steal an active repair issue."""
    run = failed_run()
    run["conclusion"] = "success"
    run["jobs"] = [
        {
            "name": recovery.DEPLOY_JOB_NAME,
            "conclusion": "success",
            "steps": [{"name": name, "conclusion": "success"} for name in recovery.SMOKES],
        }
    ]
    calls = exercise_reconcile(
        recovery,
        monkeypatch,
        run,
        [
            {
                "number": 8,
                "body": recovery.MARKER,
                "labels": [{"name": "factory:local"}],
            }
        ],
    )
    assert len(calls) == 2


@pytest.mark.parametrize("proof_available", [True, False])
def test_freeze_cli_requires_successful_repair_proof(
    recovery: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    proof_available: bool,
) -> None:
    """The real freeze CLI retries a proven fix and stays frozen on API errors."""
    factory_deploy_freeze = importlib.import_module("factory_deploy_freeze")

    def proof(run: object, repository: str) -> int:
        if not proof_available:
            raise subprocess.CalledProcessError(1, ["gh", "pr", "list"])
        return 42

    monkeypatch.setattr(recovery, "merged_repair", proof)
    monkeypatch.setitem(sys.modules, "factory_deploy_recovery", recovery)
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"workflow_runs": [failed_run()]})))
    result = factory_deploy_freeze.main(["--recover-reviewed-fix"])
    decision = json.loads(capsys.readouterr().out)
    assert result == (0 if proof_available else 1)
    assert decision["blocked"] is not proof_available
