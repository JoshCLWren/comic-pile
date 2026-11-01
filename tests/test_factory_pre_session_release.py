"""Exercise trusted lease cleanup when a factory aborts before its worker starts."""

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
    release = cleanup["steps"][2]
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


@pytest.mark.parametrize("worker", ["1", "58", "99"])
def test_cleanup_calls_existing_controller_with_run_provenance(
    tmp_path: Path, worker: str,
) -> None:
    """Execute the workflow shell against a controller stand-in, without GitHub writes."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    release = workflow["jobs"]["release_pre_session_lease"]["steps"][2]
    controller = tmp_path / ".github/scripts/factory-work-controller.py"
    controller.parent.mkdir(parents=True)
    controller.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n")
    result = subprocess.run(
        ["bash", "-c", release["run"]], cwd=tmp_path,
        env={**os.environ, "FACTORY_WORKER": worker, "GITHUB_RUN_ID": "41323597249"},
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == [
        "release", "--worker", worker, "--reason", "pre-session-abort-run-41323597249",
    ]


@pytest.mark.parametrize("worker", ["", "0", "100", "local", "58; echo injected"])
def test_cleanup_rejects_invalid_worker_before_invoking_controller(
    tmp_path: Path, worker: str,
) -> None:
    """Malformed dispatch input cannot broaden recovery or execute shell fragments."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    release = workflow["jobs"]["release_pre_session_lease"]["steps"][2]
    result = subprocess.run(
        ["bash", "-c", release["run"]], cwd=tmp_path,
        env={**os.environ, "FACTORY_WORKER": worker, "GITHUB_RUN_ID": "41323597249"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Invalid worker ID; refusing lease recovery\n"
