"""Regression coverage for factory assignment-writer authority.

Incident #2727 proved that independent assignment writers could observe the
same worker as idle and lease unrelated targets to it. Assignment authority is
therefore centralized in Fixed Model Factory Dispatcher; event workflows may
recover capacity but may only signal that dispatcher for new leases.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SCRIPTS = REPO_ROOT / ".github" / "scripts"
ASSIGN_MARKER = 'python3 "$controller" assign --worker "$worker"'
DISPATCHER = "fixed-model-factory-dispatch.yml"


def test_dispatcher_is_the_only_workflow_with_assignment_authority() -> None:
    """Only the central dispatcher may call the generic assignment mutation command."""
    writers = []
    workflows = sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        if ASSIGN_MARKER in text:
            writers.append(workflow.name)

    assert writers == [DISPATCHER]


def test_completion_drain_is_signal_only() -> None:
    """Completion events wake the writer and never read or mutate the work queue."""
    text = (WORKFLOWS / "factory-completion-drain.yml").read_text(encoding="utf-8")

    assert "gh workflow run fixed-model-factory-dispatch.yml" in text
    assert "-f mode=completion" in text
    assert "factory_full_completion_controller.py" not in text
    assert "factory-work-controller.py" not in text
    assert "gh workflow run free-model-factory-entry.yml" not in text
    assert ASSIGN_MARKER not in text
    assert 'workflows: ["Fixed Model Factory Entry"]' in text
    assert '"Fixed Model Factory Dispatcher"' not in text


def test_dispatcher_owns_demand_driven_completion_allocation() -> None:
    """The existing PR-only completion allocator executes under the writer lock."""
    dispatcher = (WORKFLOWS / DISPATCHER).read_text(encoding="utf-8")
    completion = (SCRIPTS / "factory_full_completion_controller.py").read_text(
        encoding="utf-8"
    )

    assert "- completion" in dispatcher
    assert '"$DISPATCH_MODE" == completion' in dispatcher
    assert "python3 .github/scripts/factory_full_completion_controller.py" in dispatcher
    assert "[.assignments[].worker]" in dispatcher
    assert 'dispatch_leased_worker "$worker"' in dispatcher

    assert "completion_worker_target" in completion
    assert "assign_completion_batch" in completion
    assert "assign_completion_candidate" in completion
    assert "linked_issue=None" in completion


def test_capacity_refill_recovers_then_signals_dispatcher() -> None:
    """Capacity recovery may release stale leases but never create new ones."""
    text = (WORKFLOWS / "fixed-model-factory-capacity-refill.yml").read_text(
        encoding="utf-8"
    )

    assert "gh workflow run fixed-model-factory-dispatch.yml" in text
    assert 'python3 "$controller" reconcile || true' in text
    assert ASSIGN_MARKER not in text
    assert "gh workflow run free-model-factory-entry.yml" not in text


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


def test_targeted_refill_does_not_start_roster_chain() -> None:
    """Explicit worker refill must not multiply self-perpetuating roster runs."""
    refill = (WORKFLOWS / "fixed-model-factory-capacity-refill.yml").read_text(
        encoding="utf-8"
    )
    dispatcher = (WORKFLOWS / DISPATCHER).read_text(encoding="utf-8")

    assert '-f mode=smoke -f worker="$worker"' in refill
    assert "inputs.mode == 'roster' && inputs.worker == ''" in dispatcher
