"""Exercise trusted lease cleanup when a factory aborts before its worker starts."""

import ast
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/free-model-factory-run.yml"


def test_cleanup_waits_for_factory_and_excludes_started_sessions() -> None:
    """A failed smoke releases promptly; an executing worker owns its lifecycle."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    factory = workflow["jobs"]["factory"]
    cleanup = workflow["jobs"]["release_pre_session_lease"]
    assert cleanup["needs"] == "factory"
    assert cleanup["if"] == (
        "${{ always() && needs.factory.outputs.worker_session_started != 'true' }}"
    )
    assert factory["outputs"]["worker_session_started"] == (
        "${{ steps.worker_session.outputs.started }}"
    )
    session = next(step for step in factory["steps"] if step.get("id") == "worker_session")
    assert session["run"].index("started=true") < session["run"].index(
        "bash .github/scripts/free-model-factory-worker.sh"
    )
    # Serialization must cover both jobs so a successor cannot acquire a new
    # lease for this worker while its preceding failed startup is recovering.
    assert workflow["concurrency"]["group"] == "fixed-model-factory-${{ inputs.worker }}"
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_post_session_cleanup_runs_under_worker_lock() -> None:
    """After a model session, the trusted cleanup releases both ownership ledgers."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    cleanup = workflow["jobs"]["release_post_session_lease"]
    assert cleanup["needs"] == "factory"
    assert cleanup["if"] == (
        "${{ always() && needs.factory.outputs.worker_session_started == 'true' }}"
    )
    assert workflow["concurrency"]["group"] == "fixed-model-factory-${{ inputs.worker }}"
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert cleanup["runs-on"] == "ubuntu-latest"
    assert cleanup["steps"][0]["with"] == {"ref": "main", "persist-credentials": False}
    assert cleanup["steps"][2]["uses"] == "./.github/actions/factory-state-cache"
    assert cleanup["steps"][2]["with"] == {
        "neon-api-key": "${{ secrets.NEON_API_KEY }}",
        "neon-project-id": "${{ vars.NEON_PROJECT_ID }}",
    }
    release = cleanup["steps"][3]
    assert "post-session-exit-run-${GITHUB_RUN_ID}" in release["run"]
    assert "refusing split release" in release["run"]
    assert cleanup["permissions"] == {
        "contents": "read", "issues": "write", "pull-requests": "write",
    }
    assert "factory-state-cache" not in json.dumps(workflow["jobs"]["factory"])


def test_post_session_cleanup_executes_token_bound_release(tmp_path: Path) -> None:
    """Run the real job command with a stand-in controller and restricted DSN."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    release = workflow["jobs"]["release_post_session_lease"]["steps"][3]
    controller = tmp_path / ".github/scripts/factory-work-controller.py"
    controller.parent.mkdir(parents=True)
    controller.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n")
    dsn = tmp_path / "restricted-dsn"
    dsn.write_text("test-only-connection")
    result = subprocess.run(
        ["bash", "-c", release["run"]], cwd=tmp_path,
        env={**os.environ, "FACTORY_WORKER": "45", "GITHUB_RUN_ID": "43455638659",
             "FACTORY_STATE_DSN_FILE": str(dsn)},
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == [
        "release", "--worker", "45", "--reason",
        "post-session-exit-run-43455638659",
    ]


def test_cleanup_uses_a_fresh_trusted_runner_and_workflow_token() -> None:
    """Never run recovery code or carry model credentials from the smoke checkout."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    cleanup = workflow["jobs"]["release_pre_session_lease"]
    assert cleanup["runs-on"] == "ubuntu-latest"
    assert "env" not in cleanup
    checkout = cleanup["steps"][0]
    assert checkout["uses"] == "actions/checkout@v7"
    assert checkout["with"] == {"ref": "main", "persist-credentials": False}
    assert cleanup["steps"][1]["uses"] == "./.github/actions/factory-syntax"
    neon = cleanup["steps"][2]
    assert neon["uses"] == "./.github/actions/factory-state-cache"
    assert neon["with"] == {
        "neon-api-key": "${{ secrets.NEON_API_KEY }}",
        "neon-project-id": "${{ vars.NEON_PROJECT_ID }}",
    }
    # The privileged DB action belongs to cleanup, never the model job.
    assert "factory-state-cache" not in json.dumps(workflow["jobs"]["factory"])
    assert "NEON_API_KEY" not in json.dumps(workflow["jobs"]["factory"])
    release = cleanup["steps"][3]
    assert "FACTORY_STATE_DSN_FILE" in release["run"]
    assert "refusing split release" in release["run"]
    assert release["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "FACTORY_WORKER": "${{ inputs.worker }}",
    }
    assert cleanup["permissions"] == {
        # PR-target label replacement returns 403 with pull-requests:read,
        # even though the same job can release an ordinary issue lease.
        "contents": "read", "issues": "write", "pull-requests": "write",
    }
    entry = yaml.safe_load((ROOT / ".github/workflows/free-model-factory-entry.yml").read_text())
    assert entry["permissions"]["pull-requests"] == "write"
    assert workflow["permissions"]["pull-requests"] == "write"


@pytest.mark.parametrize("worker", ["1", "58", "99", "100", "104", "107"])
def test_cleanup_calls_existing_controller_with_run_provenance(
    tmp_path: Path, worker: str,
) -> None:
    """Execute the workflow shell against a controller stand-in, without GitHub writes."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    release = workflow["jobs"]["release_pre_session_lease"]["steps"][3]
    controller = tmp_path / ".github/scripts/factory-work-controller.py"
    controller.parent.mkdir(parents=True)
    controller.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n")
    dsn = tmp_path / "restricted-dsn"
    dsn.write_text("not-a-real-connection")
    result = subprocess.run(
        ["bash", "-c", release["run"]], cwd=tmp_path,
        env={**os.environ, "FACTORY_WORKER": worker, "GITHUB_RUN_ID": "41323597249",
             "FACTORY_STATE_DSN_FILE": str(dsn)},
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == [
        "release", "--worker", worker, "--reason", "pre-session-abort-run-41323597249",
    ]


@pytest.mark.parametrize("worker", ["", "0", "00", "0104", "1000", "local", "104; echo injected"])
def test_cleanup_rejects_invalid_worker_before_invoking_controller(
    tmp_path: Path, worker: str,
) -> None:
    """Malformed dispatch input cannot broaden recovery or execute shell fragments."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    release = workflow["jobs"]["release_pre_session_lease"]["steps"][3]
    result = subprocess.run(
        ["bash", "-c", release["run"]], cwd=tmp_path,
        env={**os.environ, "FACTORY_WORKER": worker, "GITHUB_RUN_ID": "41323597249"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Invalid worker ID; refusing lease recovery\n"

def test_cleanup_refuses_label_release_without_neon_connection(tmp_path: Path) -> None:
    """Neon outage must not release GitHub labels while retaining the DB claim."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    release = workflow["jobs"]["release_pre_session_lease"]["steps"][3]
    controller = tmp_path / ".github/scripts/factory-work-controller.py"
    controller.parent.mkdir(parents=True)
    controller.write_text("raise AssertionError('controller must not run')\n")
    result = subprocess.run(
        ["bash", "-c", release["run"]], cwd=tmp_path,
        env={**os.environ, "FACTORY_WORKER": "104", "GITHUB_RUN_ID": "41323597249",
             "FACTORY_STATE_DSN_FILE": ""},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Neon factory lease connection missing" in result.stderr


def _load_controller_release(helpers: dict[str, object]):
    """Exercise the real release function without importing its GitHub CLI."""
    source = (ROOT / ".github/scripts/factory-work-controller.py").read_text()
    method = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "release_worker"
    )
    module = ast.Module(body=[method], type_ignores=[])
    namespace: dict[str, object] = {
        "REPO": "owner/repo",
        "sys": __import__("sys"),
        "list_issues": lambda: [],
        "list_prs": lambda: [],
        "owner_of": lambda labels: None,
        "labels_of": lambda item: [],
        "target_owned_by": lambda number, owner: False,
        "target_json": lambda number: {"labels": []},
        "OWNER_RE": __import__("re").compile(r"^factory:(?:unowned|[0-9]+)$"),
        "json": json,
        "release_lease": lambda *args: False,
        **helpers,
    }
    exec(compile(module, "<factory-controller-release>", "exec"), namespace)
    return namespace["release_worker"]


def test_trusted_cleanup_fails_before_github_label_mutation_if_neon_unavailable() -> None:
    calls: list[int] = []

    def fail_snapshot(repo: str, worker: str):
        raise ConnectionError("Neon unavailable")

    release = _load_controller_release({
        "worker_claim": fail_snapshot,
        "list_issues": lambda: calls.append(1) or [],
    })
    with pytest.raises(ConnectionError, match="Neon unavailable"):
        release("104", "pre-session-abort-run-43439464262")
    assert calls == []


def test_post_session_cleanup_fails_closed_on_neon_read_outage() -> None:
    """A completed worker must not release GitHub labels without its Neon claim."""
    calls: list[int] = []

    def fail_snapshot(repo: str, worker: str):
        raise ConnectionError("Neon unavailable")

    release = _load_controller_release({
        "worker_claim": fail_snapshot,
        "list_issues": lambda: calls.append(1) or [],
    })
    with pytest.raises(ConnectionError, match="Neon unavailable"):
        release("45", "post-session-exit-run-43455638659")
    assert calls == []


def test_trusted_cleanup_retry_clears_original_claim_when_labels_already_released() -> None:
    releases: list[tuple[object, ...]] = []
    release = _load_controller_release({
        "worker_claim": lambda repo, worker: ("old-claim-token", [4833, 5015]),
        "release_lease": lambda *args: releases.append(args) or True,
    })
    assert release("45", "pre-session-abort-run-43450421076") == []
    assert releases == [
        ("owner/repo", "45", "old-claim-token", "pre-session-abort-run-43450421076")
    ]



def test_trusted_exit_releases_every_original_target_without_projection_scan() -> None:
    """Linked issue and PR are sourced from the UUID claim, not stale discovery."""
    labels = {4737: "factory:20", 5055: "factory:20"}
    released = []
    events = []
    token = ("claim-20", [4737, 5055])

    def target(number: int) -> dict:
        return {
            "labels": [{"name": labels[number]}],
            **({"pull_request": {}} if number == 5055 else {}),
        }

    def update(number: int, owner: str, *, expected_owner: str) -> bool:
        assert owner == "factory:unowned" and expected_owner == "factory:20"
        labels[number] = "factory:unowned"
        return True

    release = _load_controller_release({
        "worker_claim": lambda *args: token,
        "target_json": target,
        "replace_factory_labels": update,
        "target_owned_by": lambda number, owner: labels[number] == owner,
        "record_claim_released": lambda number, worker, kind, reason: events.append((number, kind)),
        "release_lease": lambda *args: released.append(args) or True,
        "list_issues": lambda: (_ for _ in ()).throw(AssertionError("unexpected inventory scan")),
        "list_prs": lambda: (_ for _ in ()).throw(AssertionError("unexpected inventory scan")),
    })
    summary = {}
    assert release("20", "pre-session-abort-run-43603288148", details=summary) == [4737, 5055]
    assert summary["status"] == "released" and summary["claim_released"]
    assert released == [("owner/repo", "20", "claim-20", "pre-session-abort-run-43603288148")]
    assert events == [(4737, "issue"), (5055, "pr")]


def test_trusted_exit_no_claim_is_an_idempotent_noop() -> None:
    release = _load_controller_release({
        "worker_claim": lambda *args: None,
        "target_json": lambda *_: (_ for _ in ()).throw(AssertionError("unowned retry must not read")),
    })
    result = {}
    assert release("20", "post-session-exit-run-123", details=result) == []
    assert result["status"] == "already_released"
    assert result["claim_id"] is None


def test_trusted_exit_does_not_clear_reassigned_claim() -> None:
    """A new UUID between snapshot and mutation must leave both ledgers alone."""
    seen = 0
    writes = []
    leases = []

    def claim(*_args: object):
        nonlocal seen
        seen += 1
        return ("old", [5055]) if seen == 1 else ("new", [5055])

    release = _load_controller_release({
        "worker_claim": claim,
        "target_json": lambda *_: {"labels": [{"name": "factory:21"}], "pull_request": {}},
        "replace_factory_labels": lambda *a, **k: writes.append((a, k)),
        "release_lease": lambda *a: leases.append(a),
    })
    summary = {}
    assert release("21", "pre-session-abort-run-43604078425", details=summary) == []
    assert summary["status"] == "deferred"
    assert summary["deferred"] == [5055]
    assert not writes and not leases


def test_trusted_exit_reports_live_github_errors_instead_of_silent_success() -> None:
    release = _load_controller_release({
        "worker_claim": lambda *args: ("claim", [5055]),
        "target_json": lambda *_: (_ for _ in ()).throw(RuntimeError("github unavailable")),
        "release_lease": lambda *_: (_ for _ in ()).throw(AssertionError("must not release")),
    })
    summary = {}
    assert release("21", "post-session-exit-run-43604078425", details=summary) == []
    assert summary["status"] == "failed"
    assert summary["failed"] == ["5055:RuntimeError"]
