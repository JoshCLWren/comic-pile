"""Regression coverage for factory assignment-writer authority.

Incident #2727 proved that independent assignment writers could observe the
same worker as idle and lease unrelated targets to it. Assignment authority is
therefore centralized in Fixed Model Factory Dispatcher; event workflows may
only signal that dispatcher.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ASSIGN_MARKER = 'python3 "$controller" assign --worker "$worker"'
DISPATCHER = "fixed-model-factory-dispatch.yml"


def test_dispatcher_is_the_only_workflow_with_assignment_authority() -> None:
    """Only the central dispatcher may call the assignment mutation command."""
    writers = []
    for workflow in WORKFLOWS.glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        if ASSIGN_MARKER in text:
            writers.append(workflow.name)

    assert writers == [DISPATCHER]


def test_completion_drain_only_signals_dispatcher() -> None:
    """Completion events must wake the writer instead of claiming work directly."""
    text = (WORKFLOWS / "factory-completion-drain.yml").read_text(encoding="utf-8")

    assert "gh workflow run fixed-model-factory-dispatch.yml" in text
    assert "factory_full_completion_controller.py" not in text
    assert "free-model-factory-entry.yml" not in text
    assert "factory-work-controller.py" not in text
    assert 'workflows: ["Fixed Model Factory Entry"]' in text
    assert '"Fixed Model Factory Dispatcher"' not in text


def test_capacity_refill_only_signals_dispatcher() -> None:
    """Capacity events may select a worker hint but never mutate leases themselves."""
    text = (WORKFLOWS / "fixed-model-factory-capacity-refill.yml").read_text(
        encoding="utf-8"
    )

    assert "gh workflow run fixed-model-factory-dispatch.yml" in text
    assert ASSIGN_MARKER not in text
    assert "gh workflow run free-model-factory-entry.yml" not in text
    assert "factory-work-controller.py" not in text


def test_event_workflows_do_not_share_dispatcher_writer_lock() -> None:
    """Signal workflows are no longer part of assignment correctness."""
    completion = (WORKFLOWS / "factory-completion-drain.yml").read_text(
        encoding="utf-8"
    )
    refill = (WORKFLOWS / "fixed-model-factory-capacity-refill.yml").read_text(
        encoding="utf-8"
    )

    assert "group: fixed-model-factory-dispatch" not in completion
    assert "group: fixed-model-factory-dispatch" not in refill
