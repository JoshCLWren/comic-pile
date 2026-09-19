"""Regression coverage for factory assignment-writer authority.

Incident #2727 proved that independent assignment writers could observe the
same worker as idle and lease unrelated targets to it. Assignment authority is
therefore centralized in Fixed Model Factory Dispatcher; event workflows may
plan or recover capacity but may only signal that dispatcher for new leases.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SCRIPTS = REPO_ROOT / ".github" / "scripts"
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


def test_completion_drain_plans_read_only_then_signals_dispatcher() -> None:
    """Completion health/ranking survives while lease mutation stays centralized."""
    text = (WORKFLOWS / "factory-completion-drain.yml").read_text(encoding="utf-8")
    planner = (SCRIPTS / "factory_full_completion_controller.py").read_text(
        encoding="utf-8"
    )

    assert "factory_full_completion_controller.py" in text
    assert "gh workflow run fixed-model-factory-dispatch.yml" in text
    assert '-f mode=smoke -f workers="$WORKERS"' in text
    assert "gh workflow run free-model-factory-entry.yml" not in text
    assert ASSIGN_MARKER not in text
    assert 'workflows: ["Fixed Model Factory Entry"]' in text
    assert '"Fixed Model Factory Dispatcher"' not in text
    assert "plan_completion_workers" in planner
    assert "assign_candidate" not in planner
    assert "assign_completion_batch" not in planner


def test_dispatcher_accepts_one_validated_worker_batch() -> None:
    """Completion plans enter one serialized writer run instead of N pending runs."""
    text = (WORKFLOWS / DISPATCHER).read_text(encoding="utf-8")

    assert "workers:" in text
    assert 'DISPATCH_WORKERS: ${{ inputs.workers }}' in text
    assert 'workers must be a non-empty JSON array of numeric strings' in text
    assert 'Unknown batched fixed-model worker ${worker}' in text
    assert 'jq -r \'.[]\' <<< "$workers"' in text


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


def test_targeted_signals_do_not_start_roster_chains() -> None:
    """Explicit delegation must not multiply self-perpetuating roster runs."""
    completion = (WORKFLOWS / "factory-completion-drain.yml").read_text(
        encoding="utf-8"
    )
    refill = (WORKFLOWS / "fixed-model-factory-capacity-refill.yml").read_text(
        encoding="utf-8"
    )
    dispatcher = (WORKFLOWS / DISPATCHER).read_text(encoding="utf-8")

    assert '-f mode=smoke -f workers="$WORKERS"' in completion
    assert '-f mode=smoke -f worker="$worker"' in refill
    assert "inputs.worker == '' && inputs.workers == ''" in dispatcher
