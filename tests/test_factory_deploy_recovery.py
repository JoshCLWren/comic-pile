"""Regressions for bounded recovery and factory incident routing."""

import importlib.util
import io
import json
import os
import subprocess
import sys
import textwrap
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
    smoke = deploy.split("- name: Smoke production Rust health", 1)[1].split(
        "- name: Smoke production unknown API returns native Rust 404", 1
    )[0]
    assert "for attempt in $(seq 1 8)" in smoke
    assert "--header 'cache-control: no-cache'" in smoke
    assert '[[ "$status" == "200" && "$runtime" == "rust" ]]' in smoke
    assert '.build.revision == $sha' in smoke
    assert '.build.package == "comicpile-vercel-native"' in smoke
    assert '(.build.compiler | startswith("rustc "))' in smoke
    assert '.process.os == "linux"' in smoke
    assert "if [[ \"$attempt\" -lt 8 ]]" in smoke
    assert "exit 1" in smoke




@pytest.mark.parametrize("always_fail", [False, True])
def test_rust_health_smoke_retries_curl_errors_without_weakening_identity(
    tmp_path: Path, always_fail: bool
) -> None:
    """A failed curl retries; a permanently failed probe still blocks deployment."""
    workflow = (SCRIPTS.parent / "workflows" / "deploy-production.yml").read_text()
    smoke = workflow.split("      - name: Smoke production Rust health\\n", 1)[1].split(
        "      - name: Smoke production unknown API returns native Rust 404\\n", 1
    )[0]
    shell = textwrap.dedent(smoke.split("        run: |\\n", 1)[1])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    counter = tmp_path / "curl-count"
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(r"""#!/usr/bin/env bash
set -euo pipefail
count="$(cat "$FAKE_CURL_COUNT" 2>/dev/null || echo 0)"
printf '%s' "$((count + 1))" > "$FAKE_CURL_COUNT"
if [[ "$FAKE_CURL_ALWAYS_FAIL" == "1" || "$count" == "0" ]]; then
  exit 7
fi
body=""
headers=""
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --output) body="$2"; shift 2 ;;
    --dump-header) headers="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf 'HTTP/1.1 200 OK\\r\\nx-comicpile-api-runtime: rust\\r\\n' > "$headers"
printf '{"status":"ok","build":{"revision":"%s","package":"comicpile-vercel-native","compiler":"rustc 1.99.0"},"process":{"os":"linux","executable":"native_roll"}}' "$FAKE_SHA" > "$body"
printf 200
""")
    fake_curl.chmod(0o755)
    fake_sleep = bin_dir / "sleep"
    fake_sleep.write_text("#!/bin/sh\\nexit 0\\n")
    fake_sleep.chmod(0o755)
    root = SCRIPTS.parents[1]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env = dict(os.environ)
    env.update({
        "FAKE_CURL_COUNT": str(counter),
        "FAKE_CURL_ALWAYS_FAIL": "1" if always_fail else "0",
        "FAKE_SHA": sha,
        "PATH": f"{bin_dir}:{env['PATH']}",
    })
    result = subprocess.run(
        ["bash", "-c", shell], cwd=root, env=env,
        capture_output=True, text=True, check=False, timeout=30,
    )
    if always_fail:
        assert result.returncode != 0
        assert counter.read_text() == "8"
        assert "never matched the exact Rust build/process revision" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert counter.read_text() == "2"
        assert f"Production Rust identity confirmed for {sha}" in result.stdout


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


@pytest.mark.parametrize("invalid", [None, "sha", "run_id", "run_attempt"])
def test_exact_attempt_revision_artifact(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, invalid: str | None
) -> None:
    """Only matching run/attempt metadata supplies the selected main revision."""
    run = failed_run()
    run["run_attempt"] = 2
    payload = {"sha": "b" * 40, "run_id": "11", "run_attempt": "2"}
    if invalid:
        payload[invalid] = "invalid"

    def download(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert "deployment-attempt-2" in arguments
        Path(arguments[-1], "deployment-attempt.json").write_text(json.dumps(payload))
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(recovery.subprocess, "run", download)
    selected = recovery.attempt_revision(run, "example/repo")
    assert selected == (None if invalid else "b" * 40)
    body = recovery.incident_body(run, selected)
    assert f"Workflow trigger SHA: `{'a' * 40}`" in body
    assert ("unavailable" in body) is bool(invalid)
    if not invalid:
        assert f"Selected deployment attempt SHA: `{'b' * 40}`" in body


def test_missing_historical_attempt_artifact_is_truthful(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expired/missing/API-unavailable evidence is never replaced by trigger SHA."""
    run = failed_run()
    run["run_attempt"] = 1

    def missing(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, ["gh", "run", "download"])

    monkeypatch.setattr(recovery.subprocess, "run", missing)
    assert recovery.attempt_revision(run, "example/repo") is None
    assert "unavailable" in recovery.incident_body(run)


def test_revision_is_published_before_preflight_dependencies() -> None:
    """A selected checkout remains attributable even when setup/preflight fails."""
    deploy = (SCRIPTS.parent / "workflows" / "deploy-production.yml").read_text()
    preflight = deploy.split("  preflight:")[1].split("  deploy:")[0]
    assert preflight.index("Publish selected deployment revision") < preflight.index("Require Vercel token")
    assert "deployment-attempt-${{ github.run_attempt }}" in preflight
    assert 'run_attempt: $run_attempt' in preflight
    assert "steps.revision.outputs.deploy_sha" in preflight
