"""Static contracts for event-driven fixed-model capacity refill."""

from pathlib import Path


WORKFLOW = Path('.github/workflows/fixed-model-factory-capacity-refill.yml')


def _workflow_text() -> str:
    """Return the capacity-refill workflow source."""
    return WORKFLOW.read_text(encoding='utf-8')


def _outcome_gate() -> str:
    """Return the shell case statement that decides immediate capacity reuse."""
    text = _workflow_text()
    return text.split('case "$attempt_outcome" in', 1)[1].split('esac', 1)[0]


def test_healthy_entry_completion_wakes_dispatcher_for_same_worker() -> None:
    """Provider-healthy terminal outcomes request centralized immediate reuse."""
    text = _workflow_text()

    assert "workflows: ['Fixed Model Factory Entry']" in text
    assert 'types: [completed]' in text
    assert 'Attempt outcome: ' in text
    assert 'success|no_work|work_failure)' in _outcome_gate()
    assert '-f mode=roster -f worker="$worker"' in text
    assert 'gh workflow run fixed-model-factory-dispatch.yml' in text
    assert 'python3 "$controller" assign --worker "$worker"' not in text
    assert 'gh workflow run free-model-factory-entry.yml' not in text


def test_attempt_registry_pages_are_slurped_exactly_once() -> None:
    """Paginated issue comments must remain a page stream for jq to slurp once."""
    text = _workflow_text()

    assert 'gh api --paginate --slurp' not in text
    assert 'gh api --paginate \\\n                "repos/${GITHUB_REPOSITORY}/issues/1093/comments?per_page=100"' in text
    assert '| jq -rs --arg run "$COMPLETED_RUN_ID"' in text


def test_unhealthy_failure_does_not_immediately_reuse_capacity() -> None:
    """Provider/model/control-plane failures must not cause a tight redispatch loop."""
    gate = _outcome_gate()

    for outcome in (
        'provider_failure',
        'provider_throttle',
        'model_unavailable',
        'model_policy_violation',
        'environment_failure',
        'control_plane_failure',
        'unknown_failure',
    ):
        assert outcome not in gate
    assert 'capacity is not proven healthy for immediate reuse' in gate


def test_control_plane_deploy_requests_broad_dispatcher_refill() -> None:
    """A deployed refill workflow seeds capacity through the single writer."""
    text = _workflow_text()

    assert "branches: [main]" in text
    assert 'Requesting broad fixed-model capacity refill through dispatcher' in text
    assert 'gh workflow run fixed-model-factory-dispatch.yml' in text
    assert '-f mode=roster' in text


def test_stale_entry_runs_are_force_cancelled_before_reconciliation() -> None:
    """A ghost queued run must not preserve fixed-model leases forever."""
    text = _workflow_text()

    stale_scan = 'for status in queued in_progress; do'
    force_cancel = '/actions/runs/${run_id}/force-cancel'
    reconcile = 'python3 "$controller" reconcile || true'

    assert 'stale_run_seconds=7200' in text
    assert stale_scan in text
    assert force_cancel in text
    assert reconcile in text
    assert text.index(stale_scan) < text.index(force_cancel) < text.index(reconcile)


def test_refill_recovery_has_no_direct_assignment_or_entry_authority() -> None:
    """Recovery may release stale leases but may not create or launch assignments."""
    text = _workflow_text()

    assert 'python3 "$controller" reconcile || true' in text
    assert 'python3 "$controller" assign --worker "$worker"' not in text
    assert 'gh workflow run free-model-factory-entry.yml' not in text
    assert 'gh workflow run fixed-model-factory-dispatch.yml' in text
