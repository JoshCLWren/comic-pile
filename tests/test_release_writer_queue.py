"""Regression tests for issue #5752: release-writer queue and factory merge trigger.

Covers Greptile PR #3993 findings:
1. Factory releases never start - factory merges with GITHUB_TOKEN do not emit
   pull_request_target, so release-writer must be triggered explicitly.
2. Pending releases get dropped - a shared concurrency group with one pending
   slot drops queued PRs when more merges arrive.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WRITER_WORKFLOW = ROOT / ".github" / "workflows" / "release-writer.yml"
MERGE_DRAIN_WORKFLOW = (
    ROOT / ".rotisserie" / "runtime" / ".github" / "workflows" / "factory-ready-merge-drain.yml"
)


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
    assert "Fixed Model Factory Dispatch" in workflows
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


def test_merge_drain_dispatches_release_writer_after_merge() -> None:
    """Finding 1: merge-drain should explicitly dispatch release-writer for merged PR."""
    text = MERGE_DRAIN_WORKFLOW.read_text(encoding="utf-8")
    assert "release-writer.yml" in text
    assert "pr_number=${merged_pr}" in text or "pr_number=" in text
    assert "dispatch_release_writer" in text
