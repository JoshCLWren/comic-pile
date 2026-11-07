"""Regression coverage for factory assignment-writer serialization.

Incident #2727 proved that independent workflow concurrency groups let two
controllers observe the same worker as idle and lease unrelated targets to it.
Every workflow with assignment authority must therefore share one repository-
wide serialization group.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ASSIGNMENT_GROUP = "fixed-model-factory-dispatch"


def _load_workflow(filename: str) -> dict:
    """Parse a workflow file with a real YAML parser.

    Parsing with a YAML parser instead of string splitting keeps the test
    robust against indentation changes and additional jobs. The dispatcher
    now separates its long-running cadence job from the serialized writer.
    """
    import yaml

    with (WORKFLOWS / filename).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _ingress_group(workflow: dict) -> str:
    """Return the workflow-level concurrency group expression, or ""."""
    concurrency = workflow.get("concurrency") or {}
    return str(concurrency.get("group", ""))


def _ingress_queue(workflow: dict) -> str:
    """Return the workflow-level concurrency queue mode, or ""."""
    concurrency = workflow.get("concurrency") or {}
    return str(concurrency.get("queue", ""))


def _ingress_cancel(workflow: dict) -> bool:
    """Return the workflow-level cancel-in-progress flag, defaulting True."""
    concurrency = workflow.get("concurrency") or {}
    return bool(concurrency.get("cancel-in-progress", True))


def _job_group(workflow: dict) -> str:
    """Return the first job's concurrency group expression, or ""."""
    jobs = workflow.get("jobs") or {}
    for job in jobs.values():
        concurrency = job.get("concurrency") or {}
        return str(concurrency.get("group", ""))
    return ""


def _job_queue(workflow: dict) -> str:
    """Return the first job's concurrency queue mode, or ""."""
    jobs = workflow.get("jobs") or {}
    for job in jobs.values():
        concurrency = job.get("concurrency") or {}
        return str(concurrency.get("queue", ""))
    return ""


def _job_cancel(workflow: dict) -> bool:
    """Return the first job's cancel-in-progress flag, defaulting True."""
    jobs = workflow.get("jobs") or {}
    for job in jobs.values():
        concurrency = job.get("concurrency") or {}
        return bool(concurrency.get("cancel-in-progress", True))
    return True


def test_all_factory_assignment_writers_share_one_concurrency_group() -> None:
    """No assignment-capable workflow may mutate leases outside the shared lock."""
    writers = {
        "fixed-model-factory-dispatch.yml": 'python3 "$controller" assign --worker "$worker"',
        "fixed-model-factory-capacity-refill.yml": 'python3 "$controller" assign --worker "$worker"',
        "factory-completion-drain.yml": "factory_full_completion_controller.py",
    }

    for filename, assignment_marker in writers.items():
        text = (WORKFLOWS / filename).read_text(encoding="utf-8")
        assert assignment_marker in text, f"{filename} no longer matches its assignment marker"
        assert ASSIGNMENT_GROUP in text, (
            f"{filename} can assign factory work without the shared serialization group"
        )


def test_incident_writer_groups_are_not_independent() -> None:
    """The two writer groups implicated in incident #2727 must stay retired."""
    import re

    completion = (WORKFLOWS / "factory-completion-drain.yml").read_text(encoding="utf-8")
    refill = (WORKFLOWS / "fixed-model-factory-capacity-refill.yml").read_text(
        encoding="utf-8"
    )

    # Ensure the retired independent writer group is not used as an exact group value
    assert not re.search(r'(?m)^\s*group:\s*factory-completion-drain\s*$', completion)
    assert "group: fixed-model-capacity-refill-${{ github.event.workflow_run.id || github.run_id }}" not in refill
    # Sanity: the shared serialization group must still be present in both.
    assert _job_group(_load_workflow("factory-completion-drain.yml")) == ASSIGNMENT_GROUP
    assert _job_group(_load_workflow("fixed-model-factory-capacity-refill.yml")) == ASSIGNMENT_GROUP


def test_all_shared_assignment_workflows_preserve_pending_reconciliation() -> None:
    """All writers must opt into FIFO queuing; a single-mode entrant evicts waiters."""
    # Regression: migration-lane release runs were cancelled repeatedly while
    # dispatcher and completion work arrived in the same shared group.
    writers = (
        "fixed-model-factory-dispatch.yml",
        "fixed-model-factory-capacity-refill.yml",
        "factory-completion-drain.yml",
        "factory-migration-lane-release.yml",
        "free-model-factory-dispatch.yml",
    )
    for filename in writers:
        workflow = _load_workflow(filename)
        ingress = _ingress_group(workflow)
        writer = _job_group(workflow)
        assert _ingress_queue(workflow) == "single", filename
        assert _ingress_cancel(workflow) is False, filename
        # The shared assignment group must not be used at workflow ingress level; it is only allowed in the job section.
        assert ingress != ASSIGNMENT_GROUP, filename
        assert writer == ASSIGNMENT_GROUP, filename
        assert _job_queue(workflow) == "max", filename
        assert _job_cancel(workflow) is False, filename


def test_roster_cadence_waits_outside_shared_assignment_mutex() -> None:
    """Neither the normal tick nor a quota-reset sleep may hold the lease lock."""
    workflow = _load_workflow("fixed-model-factory-dispatch.yml")
    writer = workflow["jobs"]["dispatch"]
    cadence = workflow["jobs"]["roster-cadence"]
    assert writer["concurrency"]["group"] == ASSIGNMENT_GROUP
    assert writer["concurrency"]["queue"] == "max"
    assert cadence["needs"] == "dispatch"
    assert "concurrency" not in cadence
    assert cadence["permissions"]["actions"] == "write"
    assert "always()" in cadence["if"]
    assert "needs.dispatch.outputs.rotisserie_installed" in cadence["if"]
    assert "needs.dispatch.outputs.quota_deferred" in cadence["if"]

    writer_steps = str(writer["steps"])
    cadence_steps = str(cadence["steps"])
    assert "sleep 240" not in writer_steps
    assert 'sleep "$delay_seconds"' not in writer_steps
    assert "sleep 240" in cadence_steps
    assert 'sleep "$delay_seconds"' in cadence_steps

    expected_outputs = {
        "rotisserie_installed": "steps.rotisserie_install.outcome",
        "allow": "steps.api_budget.outputs.allow",
        "quota_deferred": "steps.api_budget.outputs.quota_deferred",
        "reset_epoch": "steps.api_budget.outputs.reset_epoch",
        "dispatched_count": "steps.dispatch_workers.outputs.dispatched_count",
        "dispatch_failed": "steps.dispatch_workers.outputs.dispatch_failed",
        "budget_deferred": "steps.dispatch_workers.outputs.budget_deferred",
        "budget_unreadable": "steps.dispatch_workers.outputs.budget_unreadable",
    }
    for key, source in expected_outputs.items():
        assert source in writer["outputs"][key]
    env = cadence["steps"][0]["env"]
    for key in expected_outputs:
        if key == "rotisserie_installed" or key == "allow":
            continue
        assert any(f"needs.dispatch.outputs.{key}" in value for value in env.values())


def test_migration_release_events_cannot_be_evicted_by_unrelated_label_churn() -> None:
    """Important wakeups have a distinct pending slot from irrelevant PR labels."""
    import json
    import re

    workflow = _load_workflow("factory-migration-lane-release.yml")
    group = _ingress_group(workflow)
    condition = workflow["jobs"]["release-waiter"]["if"]
    assert "factory-migration-release-pr-{0}-{1}" in group
    assert "github.event.pull_request.number" in group
    assert "github.event.action == 'closed'" in group
    assert "github.event.action == 'converted_to_draft'" in group
    assert "&& 'reconcile' || 'other'" in group

    def label_filter(expression: str) -> set[str]:
        match = re.search(r"fromJSON\\('(?P<labels>\\[[^']+\\])'\\)", expression)
        assert match, expression
        return set(json.loads(match.group("labels")))

    assert label_filter(group) == label_filter(condition)
    assert "factory:migration-wait" in label_filter(group)
    assert _ingress_queue(workflow) == "single"
    assert _job_queue(workflow) == "max"
