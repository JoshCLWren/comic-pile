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


def test_dispatcher_installs_exact_rotisserie_revision_before_assignment():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    pin = "0067e8c49cb3a3142a04f6c56f19795a1e81ad3c"
    assert 'git -C "$checkout" checkout --quiet --detach' in workflow
    assert pin in workflow
    assert 'pipx install "$checkout"' in workflow
    assert "rotisserie --help >/dev/null" in workflow
    assert workflow.index("Install pinned Rotisserie decision CLI") < workflow.index(
        "Resolve and dispatch fixed workers"
    )


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


def test_private_rotisserie_secret_has_safe_ssh_preflight():
    """Secret parsing and actual repo authorization must precede the pipx install."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    install = workflow.split("Install pinned Rotisserie decision CLI", 1)[1].split(
        "Ensure GitHub CLI supports JSON PR checks", 1
    )[0]
    assert 'ROTISSERIE_DEPLOY_KEY: ${{ secrets.ROTISSERIE_DEPLOY_KEY }}' in install
    assert 'ssh-keygen -y -P \'\' -f "$ssh_dir/id_ed25519"' in install
    assert 'ssh-keygen -lf "$ssh_dir/id_ed25519.pub" -E sha256' in install
    assert 'git ls-remote ' in install
    assert 'git@github.com:JoshCLWren/rotisserie.git HEAD' in install
    assert install.index("ssh-keygen -lf") < install.index("git ls-remote")
    assert install.index("git ls-remote") < install.index("git clone --quiet")
    assert install.index("git clone --quiet") < install.index('pipx install "$checkout"')
    assert 'git@github.com:JoshCLWren/rotisserie.git "$checkout"' in install
    assert "git+ssh://" not in install
    assert "StrictHostKeyChecking=yes" in install
    assert 'trap \'rm -rf "$ssh_dir"\' EXIT' in install


def test_dispatch_fails_closed_when_actions_installation_budget_is_low_or_unreadable():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    gate = workflow.split("Gate factory dispatch on Actions REST quota", 1)[1].split(
        "Reconcile serialized migration finalization lane", 1
    )[0]
    assert "gh api rate_limit" in gate
    assert "GH_TOKEN: ${{ github.token }}" in gate
    assert "remaining < 1200" in gate
    assert 'echo "allow=false" >> "$GITHUB_OUTPUT"' in gate
    assert 'echo "allow=true" >> "$GITHUB_OUTPUT"' in gate

    for step in (
        "Reconcile serialized migration finalization lane",
        "Check main health (block merges onto red main)",
        "Reconcile unowned factory CI PRs",
        "Trigger merge drain on dispatcher cadence",
        "Expire stale factory PR attempts",
        "Resolve and dispatch fixed workers",
    ):
        section = workflow.split("- name: " + step, 1)[1].split("run: |", 1)[0]
        assert "if: steps.api_budget.outputs.allow == 'true'" in section


def test_dispatch_batch_checks_live_quota_and_stops_roster_chain_at_reserve():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    batch = workflow.split("Dispatching workers through centralized assignment:", 1)[1].split(
        "Self-perpetuate roster cadence", 1
    )[0]
    assert "gh api rate_limit --jq '.resources.core.remaining'" in batch
    assert "remaining_core < 450" in batch
    assert "budget_deferred=true" in batch
    assert 'echo "budget_deferred=${budget_deferred}" >> "$GITHUB_OUTPUT"' in batch
    chain = workflow.split("- name: Self-perpetuate roster cadence", 1)[1].split("run: |", 1)[0]
    assert "steps.api_budget.outputs.allow == 'true'" in chain
    assert "steps.dispatch_workers.outputs.budget_deferred != 'true'" in chain
