"""Static contracts for event-driven fixed-model capacity refill."""

from pathlib import Path


WORKFLOW = Path('.github/workflows/fixed-model-factory-capacity-refill.yml')


def _workflow_text() -> str:
    """Return the capacity-refill workflow source."""
    return WORKFLOW.read_text(encoding='utf-8')


def test_successful_entry_completion_refills_same_worker() -> None:
    """Healthy completed capacity must request another assignment immediately."""
    text = _workflow_text()

    assert "workflows: ['Fixed Model Factory Entry']" in text
    assert 'types: [completed]' in text
    assert 'Attempt outcome: ' in text
    assert 'if [[ "$attempt_outcome" != success ]]' in text
    assert 'workers="$(jq -nc --arg worker "$worker" \'[$worker]\')"' in text
    assert 'python3 "$controller" assign --worker "$worker"' in text
    assert 'gh workflow run free-model-factory-entry.yml --ref main -f worker="$worker"' in text


def test_attempt_registry_pages_are_slurped_exactly_once() -> None:
    """Paginated issue comments must remain a page stream for jq to slurp once."""
    text = _workflow_text()

    assert 'gh api --paginate --slurp' not in text
    assert 'gh api --paginate \\\n                "repos/${GITHUB_REPOSITORY}/issues/1093/comments?per_page=100"' in text
    assert '| jq -rs --arg run "$COMPLETED_RUN_ID"' in text


def test_failure_does_not_immediately_reuse_unhealthy_capacity() -> None:
    """Provider/control-plane failures must not cause a tight redispatch loop."""
    text = _workflow_text()

    assert 'capacity is not proven healthy for immediate reuse' in text
    assert 'exit 0' in text


def test_control_plane_deploy_bootstraps_every_configured_slot() -> None:
    """A deployed refill workflow must seed the fleet without depending on cron."""
    text = _workflow_text()

    assert "branches: [main]" in text
    assert "$5 == \"dispatcher\" {print $1}" in text
    assert 'Bootstrapping all configured fixed-model slots' in text
    assert 'busy workers return `none`' in text


def test_stale_entry_runs_are_force_cancelled_before_reconciliation() -> None:
    """A ghost queued run must not preserve fixed-model leases forever."""
    text = _workflow_text()

    assert 'stale_run_seconds=7200' in text
    assert 'status in queued in_progress' not in text
    assert 'for status in queued in_progress; do' in text
    assert '/actions/runs/${run_id}/force-cancel' in text
    assert 'python3 "$controller" reconcile || true' in text


def test_dispatch_failure_releases_assignment_and_continues_batch() -> None:
    """One GitHub dispatch failure must not strand its lease or stop the fleet."""
    text = _workflow_text()

    assert 'python3 "$controller" release --worker "$worker" || true' in text
    assert 'failures=$((failures + 1))' in text
    assert 'all other slots were still attempted' in text
