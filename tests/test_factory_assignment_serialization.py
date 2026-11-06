"""Regression coverage for factory assignment-writer serialization.

Incident #2727 proved that independent workflow concurrency groups let two
controllers observe the same worker as idle and lease unrelated targets to it.
Every workflow with assignment authority must therefore share one repository-
wide serialization group.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ASSIGNMENT_GROUP = "group: fixed-model-factory-dispatch"


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
    completion = (WORKFLOWS / "factory-completion-drain.yml").read_text(
        encoding="utf-8"
    )
    refill = (WORKFLOWS / "fixed-model-factory-capacity-refill.yml").read_text(
        encoding="utf-8"
    )

    # Ensure the retired independent writer group is not used as an exact group value
    assert not re.search(r'(?m)^\s*group:\s*factory-completion-drain\s*$', completion)
    assert "group: fixed-model-capacity-refill-${{ github.event.workflow_run.id || github.run_id }}" not in refill


def test_all_shared_assignment_workflows_preserve_pending_reconciliation() -> None:
    """All writers must opt into FIFO queuing; a single-mode entrant evicts waiters."""
    import re
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
        workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
        ingress = workflow.split("concurrency:", 1)[1].split("\njobs:", 1)[0]
        writer = workflow.split("\njobs:", 1)[1]
        assert "queue: single" in ingress, filename
        assert "cancel-in-progress: false" in ingress, filename
        # The shared assignment group must not be used at workflow ingress level; it is only allowed in the job section.
        assert not re.search(r'(?m)^\s*group:\s*fixed-model-factory-dispatch\s*$', ingress), filename
        assert ASSIGNMENT_GROUP in writer, filename
        assert "queue: max" in writer, filename
        assert "cancel-in-progress: false" in writer, filename
