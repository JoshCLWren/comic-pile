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

    assert "queue: single" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "queue: max" not in workflow
    assert "- cron: '7 * * * *'" in workflow
    assert "Self-perpetuate roster cadence" in workflow
    assert "inputs.mode == 'roster'" in workflow
    assert "sleep 240" in workflow


def test_roster_tick_defaults_to_twelve_workers_with_source_diverse_seed():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'max_per_tick="${MAX_WORKERS_PER_TICK:-12}"' in workflow
    assert 'max_per_tick="${MAX_WORKERS_PER_TICK:-3}"' not in workflow
    assert "source_seed=" in workflow
    assert "source-diverse seed" in workflow
    assert 'python3 "$controller" capacity' in workflow
    assert "python3 .github/scripts/factory-work-controller.py stale" in workflow
    assert ".github/scripts/stale_pr_decay.py" in workflow
    assert 'jq -c --argjson n "$remaining" \'.[0:$n]\'' in workflow
    assert "OmniRoute free-entry cap is exhausted" in workflow
    assert workflow.index("Expire stale factory PR attempts") < workflow.index(
        "Resolve and dispatch fixed workers"
    )
    assert workflow.index("python3 .github/scripts/factory-work-controller.py stale") < workflow.index(
        'python3 "$controller" reconcile'
    )
    assert workflow.index('python3 "$controller" reconcile') < workflow.index(
        'python3 "$controller" capacity'
    )


def test_dispatch_assigned_worker_counts_successful_entry_dispatches_not_kind_none():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "dispatched_count=0" in workflow
    assert "dispatched_count=$((dispatched_count + 1))" in workflow
    # kind=none must remain an uncounted success: no increment on that branch
    none_branch = workflow.split("none)", 1)[1].split("issue|pr)", 1)[0]
    assert "dispatched_count" not in none_branch
    # the increment sits on the successful gh workflow run branch
    assert workflow.index("dispatched_count=$((dispatched_count + 1))") < workflow.index(
        "dispatch_assigned_worker \"$worker\" || dispatch_failures"
    )


def test_dispatch_step_emits_dispatched_count_and_dispatch_failed_outputs():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    dispatch_step = workflow.split("Resolve and dispatch fixed workers", 1)[1].split(
        "Self-perpetuate roster cadence", 1
    )[0]
    assert "id: dispatch_workers" in workflow
    assert 'echo "dispatched_count=${dispatched_count}" >> "$GITHUB_OUTPUT"' in dispatch_step
    assert 'echo "dispatch_failed=false" >> "$GITHUB_OUTPUT"' in dispatch_step
    assert 'echo "dispatch_failed=true" >> "$GITHUB_OUTPUT"' in dispatch_step
    assert 'echo "${dispatch_failures} worker dispatch(es) failed after retries' in dispatch_step


def test_capacity_exhausted_early_exit_is_trustworthy_zero():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "OmniRoute free-entry cap is exhausted" in workflow
    cap_branch = workflow.split("OmniRoute free-entry cap is exhausted", 1)[1][:400]
    assert 'echo "dispatched_count=0" >> "$GITHUB_OUTPUT"' in cap_branch
    assert 'echo "dispatch_failed=false" >> "$GITHUB_OUTPUT"' in cap_branch


def test_roster_chain_gates_on_dispatched_count_and_dispatch_failed():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    chain_step = workflow.split("Self-perpetuate roster cadence", 1)[1]
    assert "steps.dispatch_workers.outputs.dispatched_count" in chain_step
    assert "steps.dispatch_workers.outputs.dispatch_failed" in chain_step
    assert '[[ "$dispatch_failed" == "true" || ( "$dispatched_count" =~ ^[0-9]+$ && "$dispatched_count" -gt 0 ) ]]' in chain_step
    assert '[[ "$dispatched_count" == "0" && "$dispatch_failed" == "false" ]]' in chain_step
    assert "Trustworthy zero-work tick: ending bounded roster session" in chain_step
    # chained successor still sleeps then triggers the roster mode
    assert "sleep 240" in chain_step
    assert "-f mode=roster" in chain_step


def test_roster_chain_step_still_fires_on_always_for_schedule_or_roster():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "if: always() && (github.event_name == 'schedule' || (github.event_name == 'workflow_dispatch' && inputs.mode == 'roster'))"
        in workflow
    )
    assert "- cron: '7 * * * *'" in workflow
    assert "queue: single" in workflow
