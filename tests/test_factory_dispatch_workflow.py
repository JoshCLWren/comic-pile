"""Regression coverage for provider-derived dispatcher smoke selection."""
from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "fixed-model-factory-dispatch.yml"
)


# Keep dispatcher assertions tied to the checked-in workflow contract.
# These assertions protect the control-plane race handling, not provider policy.
def test_push_smoke_workers_are_derived_from_current_provider_rows():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workers='[\"6\",\"39\",\"46\"]'" not in workflow
    assert "!seen[$2]++ {print $1}" in workflow
    assert '"$manifest"' in workflow
    assert ".github/scripts/factory_provider_candidates.py" in workflow
    assert ".github/scripts/factory_candidate_health.py" in workflow


def test_stale_run_cancellation_retries_transient_status_race():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "cancel_succeeded=false" in workflow
    assert "for _ in {1..15}; do" in workflow
    assert '[[ "$current_status" == completed ]]' in workflow
    assert '[[ "$current_status" == queued || "$current_status" == in_progress ]]' in workflow
    assert 'cancel_output=""' in workflow
    assert 'grep -qi "workflow run that is completed"' in workflow
    assert 'status_from_cancel=true' in workflow
    assert 'if [[ "$status_from_cancel" != true ]]; then' in workflow


def test_roster_dispatch_mode_cannot_fall_through_to_smoke_selection():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "mode:" in workflow
    assert "default: smoke" in workflow
    assert '"$EVENT_NAME" == workflow_dispatch && "$DISPATCH_MODE" == roster' in workflow
    assert "-f mode=roster" in workflow


def test_recovery_watchdog_dispatches_explicit_roster_mode():
    recovery = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "fixed-model-factory-dispatch-recovery.yml"
    ).read_text(encoding="utf-8")

    assert "-f mode=roster" in recovery


def test_roster_chain_is_serialized_and_keeps_hourly_watchdog():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "cancel-in-progress: false" in workflow
    assert "- cron: '7 * * * *'" in workflow
    assert "Self-perpetuate roster cadence" in workflow
    assert "inputs.mode == 'roster'" in workflow
    assert "sleep 240" in workflow
