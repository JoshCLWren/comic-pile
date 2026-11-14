"""Regression checks for the completion drain's signal-only dispatcher handoff."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/factory-completion-drain.yml"


def steps() -> list[dict]:
    with WORKFLOW.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)["jobs"]["drain"]["steps"]


def test_completion_drain_consumes_selected_workers_not_empty_assignments() -> None:
    """The signal-only controller intentionally returns assignments=[] forever."""
    batch = next(step for step in steps() if step.get("id") == "batch")
    script = batch["run"]
    assert "factory_full_completion_controller.py" in script
    assert ".selected_workers" in script
    assert ".assignments" not in script
    assert "workers=$workers" in script


def test_completion_drain_wakes_dispatcher_without_claiming_or_releasing() -> None:
    """Only the serialized dispatcher may claim factory issue/PR leases."""
    wake = next(step for step in steps() if step.get("id") == "wakeups")
    script = wake["run"]
    assert wake["if"] == "steps.batch.outputs.workers != '[]'"
    assert "gh workflow run fixed-model-factory-dispatch.yml" in script
    assert '-f worker="$worker"' in script
    assert "free-model-factory-entry.yml" not in script
    assert "factory-work-controller.py" in script  # comment documenting ownership
    assert " assign --worker " not in script
    assert " release --worker " not in script
    assert "signaled=$signaled" in script
    assert '[[ "$worker" =~ ^[1-9][0-9]*$ ]]' in script


def test_completion_drain_reports_dispatched_wakeups_not_fake_assignments() -> None:
    report = next(
        step for step in steps()
        if step.get("name") == "Report demand-driven allocation"
    )
    assert report["env"]["SIGNALS"] == "${{ steps.wakeups.outputs.signaled }}"
    assert "dispatcher_wakeups=" in report["run"]
    assert "dispatched=${ASSIGNED" not in report["run"]


def test_completion_drain_uses_explicit_signals_not_recursive_workflow_events() -> None:
    """One worker wakeup, no dispatcher/worker workflow_run feedback paths."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_run:" not in workflow
    assert "workflow_dispatch:" in workflow
    assert "cron: '*/5 * * * *'" in workflow


def test_worker_exit_dispatches_completion_after_releasing_lease() -> None:
    """A worker's completion, even on failure, wakes the trusted dispatcher."""
    entry = ROOT / ".github/workflows/free-model-factory-entry.yml"
    with entry.open(encoding="utf-8") as stream:
        jobs = yaml.safe_load(stream)["jobs"]
    worker = jobs["run"]
    wake = jobs["signal_completion"]
    assert "free-model-factory-run.yml" in worker["uses"]
    assert wake["needs"] == "run"
    assert "always()" in wake["if"]
    assert wake["permissions"]["actions"] == "write"
    script = wake["steps"][0]["run"]
    assert "gh workflow run factory-completion-drain.yml" in script
    assert "--ref main" in script
    assert "free-model-factory-entry.yml" not in script
    assert "factory-work-controller.py" not in script
