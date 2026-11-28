"""Regression tests for issue #5752: release-writer queue and factory merge trigger.

Covers Greptile PR #3993 findings:
1. Factory releases never start - factory merges with GITHUB_TOKEN do not emit
   pull_request_target, so release-writer must be triggered explicitly.
2. Pending releases get dropped - a shared concurrency group with one pending
   slot drops queued PRs when more merges arrive.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
RELEASE_WRITER_WORKFLOW = WORKFLOWS_DIR / "release-writer.yml"


def _release_writer() -> dict:
    return yaml.safe_load(RELEASE_WRITER_WORKFLOW.read_text(encoding="utf-8"))


def test_release_writer_uses_per_pr_concurrency_group() -> None:
    """Finding 2: different merged PRs must not replace each other's pending run."""
    workflow = _release_writer()
    concurrency = workflow["concurrency"]
    assert concurrency["cancel-in-progress"] is False
    group = str(concurrency["group"])
    assert "pull_request.number" in group or "inputs.pr_number" in group
    # A static single queue drops pending PRs when a third merge arrives.
    assert group != "release-writer"


def test_release_writer_triggers_on_merge_drain_completion() -> None:
    """Finding 1: factory merge-drain completions must trigger release recovery."""
    workflow = _release_writer()
    triggers = workflow.get(True) or workflow.get("on") or {}
    workflow_run = triggers.get("workflow_run") or {}
    workflows = workflow_run.get("workflows") or []
    assert "Factory Ready Merge Drain" in workflows
    assert "Fixed Model Factory Dispatcher" in workflows
    types = workflow_run.get("types") or []
    assert "completed" in types


def test_release_writer_dispatches_missed_prs_after_merge_drain() -> None:
    """Finding 1: workflow_run path dispatches exact PR numbers, not a broad scan."""
    workflow = _release_writer()
    jobs = workflow["jobs"]
    dispatch_job = jobs.get("dispatch-missed")
    assert dispatch_job is not None, "dispatch-missed job required for factory merge recovery"
    condition = str(dispatch_job.get("if", ""))
    assert "workflow_run" in condition
    steps = dispatch_job.get("steps") or []
    run_scripts = "\n".join(str(step.get("run", "")) for step in steps)
    assert "gh workflow run release-writer.yml" in run_scripts
    assert "pr_number" in run_scripts
    # Bounded lookback, not historical reconciliation.
    assert "30 minutes ago" in run_scripts or "minutes ago" in run_scripts
    assert "--limit" in run_scripts or "head -20" in run_scripts


def test_generate_and_persist_only_handle_exact_pr_events() -> None:
    """workflow_run recovery dispatches; it must not run model/persist directly."""
    workflow = _release_writer()
    generate_if = str(workflow["jobs"]["generate"].get("if", ""))
    assert "workflow_dispatch" in generate_if
    assert "pull_request_target" in generate_if
    assert "workflow_run" not in generate_if


def test_workflow_run_names_match_installed_merge_workflows() -> None:
    """Finding 1: recovery triggers must name real workflow `name:` values exactly.

    GitHub matches ``workflow_run.workflows`` against the triggering workflow's
    ``name:`` field, not its filename. A stale or invented name silently never
    fires, which is the original 'factory releases never start' defect.
    """
    workflow = _release_writer()
    triggers = workflow.get(True) or workflow.get("on") or {}
    configured = set((triggers.get("workflow_run") or {}).get("workflows") or [])
    assert configured, "workflow_run must name at least one factory merge workflow"

    installed_names: set[str] = set()
    for path in WORKFLOWS_DIR.glob("*.yml"):
        parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        name = parsed.get("name")
        if isinstance(name, str):
            installed_names.add(name)

    unknown = configured - installed_names
    assert not unknown, f"workflow_run names do not match any installed workflow: {sorted(unknown)}"


def test_release_writer_triggers_recovery_after_successful_deploy() -> None:
    """A missed or failed writer event is retried from deployed provenance."""
    workflow = _release_writer()
    triggers = workflow.get(True) or workflow.get("on") or {}
    workflow_run = triggers.get("workflow_run") or {}
    assert "Deploy Production" in (workflow_run.get("workflows") or [])
    assert "completed" in (workflow_run.get("types") or [])


def test_recovery_job_selects_oldest_missing_deployed_source() -> None:
    """Recovery uses the bounded selector, then dispatches one exact PR run."""
    workflow = _release_writer()
    recover = workflow["jobs"].get("recover")
    assert recover is not None, "deployment-driven recovery job is required"
    condition = str(recover.get("if", ""))
    assert "Deploy Production" in condition
    assert "success" in condition
    run_scripts = "\n".join(str(step.get("run", "")) for step in recover.get("steps") or [])
    assert "release_recovery.py select" in run_scripts
    assert "--lookback-hours" in run_scripts
    assert "gh workflow run release-writer.yml" in run_scripts
    assert "pr_number" in run_scripts
    # Recovery dispatches; the model and publisher jobs remain separate.
    assert "release_reconcile.py" not in run_scripts


def test_dispatch_missed_ignores_deploy_completion() -> None:
    """The fast factory path and deployment recovery must not double-dispatch."""
    workflow = _release_writer()
    dispatch_condition = str(workflow["jobs"]["dispatch-missed"].get("if", ""))
    assert "Deploy Production" in dispatch_condition
    assert "!=" in dispatch_condition


def test_persist_reproves_deployment_before_loading_credentials() -> None:
    """An undeployed merge must never be announced (issue #4810)."""
    workflow = _release_writer()
    persist = workflow["jobs"]["persist"]
    checkout = (persist.get("steps") or [])[0]
    assert checkout.get("with", {}).get("fetch-depth") == 0
    run_scripts = [str(step.get("run", "")) for step in persist.get("steps") or []]
    verify_index = next(
        index for index, script in enumerate(run_scripts) if "verify-deployed" in script
    )
    credential_index = next(
        index for index, script in enumerate(run_scripts) if "add-mask" in script
    )
    assert verify_index < credential_index


def test_persist_grounds_complete_test_only_candidates() -> None:
    """Developer-only test diffs are recorded internal, never shown to readers."""
    workflow = _release_writer()
    run_scripts = "\n".join(
        str(step.get("run", ""))
        for step in workflow["jobs"]["persist"].get("steps") or []
    )
    assert "release_recovery.py ground-candidate" in run_scripts


def test_recovery_select_output_is_captured_for_failure_report() -> None:
    """A failed selection still leaves a bounded log for the summary (issue #5693)."""
    workflow = _release_writer()
    steps = workflow["jobs"]["recover"].get("steps") or []
    select_step = next(step for step in steps if step.get("id") == "select")
    script = str(select_step.get("run", ""))
    assert "release_recovery.py select" in script
    assert "tee" in script
    assert "RUNNER_TEMP" in script


def test_recovery_failure_is_visible_as_check_and_summary() -> None:
    """Failed recovery emits an error annotation and a still-missing PR list."""
    workflow = _release_writer()
    steps = workflow["jobs"]["recover"].get("steps") or []
    report_steps = [
        step
        for step in steps
        if "failure()" in str(step.get("if", ""))
        and "::error::" in str(step.get("run", ""))
    ]
    assert report_steps, "a failed recovery selection must produce a check error"
    summary_scripts = "\n".join(
        str(step.get("run", ""))
        for step in steps
        if "GITHUB_STEP_SUMMARY" in str(step.get("run", ""))
    )
    assert "Still-missing PRs" in summary_scripts
    assert "MISSING_PRS" in summary_scripts
    assert "SELECT_OUTCOME" in summary_scripts
    assert "Selection did not complete" in summary_scripts


def test_summary_fallback_guard_runs_on_failure_outputs() -> None:
    """The real summary condition fires for values a failed select can emit.

    A failed selection leaves MISSING_PRS unset, while an empty successful
    selection renders it as the literal '[]'. Both must enter the fallback
    that lists the still-missing PRs (issue #5693). The guard is extracted
    from the workflow and evaluated by bash rather than asserted as text.
    """
    workflow = _release_writer()
    steps = workflow["jobs"]["recover"].get("steps") or []
    summary = next(
        step for step in steps if "GITHUB_STEP_SUMMARY" in str(step.get("run", ""))
    )
    script = str(summary.get("run", ""))
    guard = next(
        line.strip().removeprefix("if ").removesuffix("; then")
        for line in script.splitlines()
        if line.strip().startswith("if ") and "missing_prs" in line
    )
    assert guard.startswith("[[") and guard.endswith("]]")

    def evaluate(missing_prs: str, outcome: str) -> int:
        result = subprocess.run(
            ["bash", "-c", guard],
            env={**os.environ, "MISSING_PRS": missing_prs, "SELECT_OUTCOME": outcome},
            capture_output=True,
            text=True,
            check=False,
        )
        assert not result.stderr, result.stderr
        return result.returncode

    # The two values the failure path can produce both enter the fallback.
    assert evaluate("", "failure") == 0
    assert evaluate("[]", "failure") == 0
    # A real listing on a successful selection must not enter the fallback.
    assert evaluate("[42]", "success") == 1
    assert evaluate("[]", "success") == 1
