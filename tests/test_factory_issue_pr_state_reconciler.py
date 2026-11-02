"""Regression coverage for scheduled factory issue-state reconciliation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"
WORKFLOW = Path(".github/workflows/factory-issue-pr-state-reconciler.yml")
POLICY_SCRIPT = SCRIPTS / "factory_issue_pr_state_policy.py"


def _load_module(name: str, path: Path) -> ModuleType:
    """Load a factory script as a module from its on-disk path."""
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _policy() -> ModuleType:
    """Load issue-state policy after work-policy is importable."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    _load_module("factory_work_policy", SCRIPTS / "factory_work_policy.py")
    return _load_module("factory_issue_pr_state_policy", POLICY_SCRIPT)


def _reconcile_issue_body(workflow: str) -> str:
    """Return the bash reconcile_issue function from the workflow file."""
    start = workflow.index("reconcile_issue() {")
    end = workflow.index("if [[ \"$EVENT_NAME\" == 'pull_request_target' ]]", start)
    return workflow[start:end]


def _iso_timestamp(epoch: int) -> str:
    """Return a GitHub-style UTC timestamp for an epoch."""
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _issue_payload(labels: list[str], updated_at: str | None) -> dict[str, object]:
    """Build the decoded issue shape consumed by the lease policy."""
    return {
        "labels": [{"name": label} for label in labels],
        "updated_at": updated_at,
    }


def test_factory_issue_state_reconciler_has_periodic_sweep() -> None:
    """Old orphaned issue labels must be repaired without a new PR event."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "  schedule:" in workflow
    assert "    - cron: '*/15 * * * *'" in workflow


def test_ralph_status_blocked_issue_is_not_rewritten() -> None:
    """A ralph-status:blocked issue must not get factory labels rewritten."""
    policy = _policy()
    work_policy = sys.modules["factory_work_policy"]

    assert policy.issue_labels_block_reconciliation(
        ["factory", "factory:unowned", "factory:blocked", "ralph-status:blocked"]
    )
    for label in work_policy.BLOCKED_LABELS:
        assert policy.issue_labels_block_reconciliation([label]), label
    assert not policy.issue_labels_block_reconciliation(
        ["factory", "factory:unowned", "ralph-status:pending"]
    )


def test_blocked_labels_cli_reports_skip_for_ralph_status_blocked() -> None:
    """The reconciler CLI must report blocked so bash returns before a rewrite."""
    blocked = subprocess.run(
        [
            sys.executable,
            str(POLICY_SCRIPT),
            "--blocked-by-labels-json",
            json.dumps(["factory", "factory:unowned", "ralph-status:blocked"]),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert blocked.stdout.strip() == "blocked"

    allowed = subprocess.run(
        [
            sys.executable,
            str(POLICY_SCRIPT),
            "--blocked-by-labels-json",
            json.dumps(["factory", "factory:unowned", "ralph-status:pending"]),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert allowed.stdout.strip() == "ok"


def test_reconcile_issue_skips_blocked_labels_before_replace() -> None:
    """Sweep and PR paths skip inside reconcile_issue, before label replacement.

    The workflow stays enabled; only issues matching claim-policy BLOCKED_LABELS
    are left alone.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    body = _reconcile_issue_body(workflow)

    assert "if: false" not in workflow
    assert "    - cron: '*/15 * * * *'" in workflow
    skip_at = body.index("--blocked-by-labels-json")
    replace_at = body.index('replace_issue_state "$issue" "$stage"')
    assert skip_at < replace_at
    assert "skipped (blocked labels)" in body
    assert "return 0" in body[skip_at:replace_at]
    assert '[[ "$blocked" == "blocked" ]]' in body
    policy_source = POLICY_SCRIPT.read_text(encoding="utf-8")
    assert "from factory_work_policy import (" in policy_source
    assert "BLOCKED_LABELS" in policy_source
    assert "lease_is_stale" in policy_source
    assert "set(labels) & BLOCKED_LABELS" in policy_source


def test_manual_only_body_blocks_reconciliation() -> None:
    """A standalone manual-only directive must skip factory label rewrites."""
    policy = _policy()

    assert policy.body_blocks_reconciliation(
        "<!-- factory-execution:manual-only -->\nHold this factory PR.\n"
    )
    assert not policy.body_blocks_reconciliation("Ordinary autonomous factory work.\n")
    assert not policy.body_blocks_reconciliation(
        "To opt out, use `<!-- factory-execution:manual-only -->`."
    )
    assert policy.body_blocks_reconciliation("Hold this factory PR.\nmanual-only\n")
    assert not policy.body_blocks_reconciliation("Discussing a manual-only hold in prose.\n")


def test_blocked_by_body_cli_reports_skip_for_manual_only(tmp_path: Path) -> None:
    """The reconciler CLI must report blocked so bash returns before a rewrite."""
    hold = tmp_path / "hold.md"
    hold.write_text(
        "<!-- factory-execution:manual-only -->\nHold this factory PR.\n",
        encoding="utf-8",
    )
    blocked = subprocess.run(
        [
            sys.executable,
            str(POLICY_SCRIPT),
            "--blocked-by-body-file",
            str(hold),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert blocked.stdout.strip() == "blocked"

    ordinary = tmp_path / "ordinary.md"
    ordinary.write_text("Ordinary autonomous factory work.\n", encoding="utf-8")
    allowed = subprocess.run(
        [
            sys.executable,
            str(POLICY_SCRIPT),
            "--blocked-by-body-file",
            str(ordinary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert allowed.stdout.strip() == "ok"


def test_reconcile_issue_skips_manual_only_before_replace() -> None:
    """Open PRs with the marker must not be rewritten to factory:unowned.

    ``gh issue list --label factory`` includes pull requests, so the body
    skip has to live inside reconcile_issue with the BLOCKED_LABELS skip.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    body = _reconcile_issue_body(workflow)

    skip_at = body.index("--blocked-by-body-file")
    replace_at = body.index('replace_issue_state "$issue" "$stage"')
    assert skip_at < replace_at
    assert "skipped (manual-only)" in body
    assert "return 0" in body[skip_at:replace_at]
    assert '[[ "$blocked" == "blocked" ]]' in body[skip_at:replace_at]


def test_fresh_local_lease_is_preserved_over_historical_pr_history() -> None:
    """A live local claim must survive a sweep that sees only closed PRs.

    #4457/#4345: applying factory:local + factory:building + ralph-status,
    then a historical-PR sweep replaces it with factory:unowned. The issue is
    still being edited, so its updated_at proves the lease is fresh.
    """
    policy = _policy()
    now = 1_800_000_000

    assert policy.lease_action_for_issue(
        _issue_payload(
            ["factory", "factory:local", "factory:building", "ralph-status:in-progress"],
            _iso_timestamp(now - 5),
        ),
        now_epoch=now,
    ) == policy.LEASE_ACTION_HOLD_LOCAL


def test_local_lease_with_unknown_activity_is_preserved() -> None:
    """Missing freshness evidence is unknown, not stale, so the lease holds."""
    policy = _policy()
    now = 1_800_000_000

    assert policy.lease_action_for_issue(
        _issue_payload(["factory", "factory:local"], None),
        now_epoch=now,
    ) == policy.LEASE_ACTION_HOLD_LOCAL


def test_provably_stale_local_lease_falls_through_to_history() -> None:
    """The shared local lease TTL still permits an authoritative release."""
    policy = _policy()
    now = 1_800_000_000
    labels = ["factory", "factory:local", "factory:building"]

    assert policy.lease_action_for_issue(
        _issue_payload(labels, _iso_timestamp(now - 3601)),
        now_epoch=now,
    ) == policy.LEASE_ACTION_RECONCILE
    # Exactly at the TTL is not yet stale.
    assert policy.lease_action_for_issue(
        _issue_payload(labels, _iso_timestamp(now - 3600)),
        now_epoch=now,
    ) == policy.LEASE_ACTION_HOLD_LOCAL


def test_local_lease_with_redundant_unowned_still_holds() -> None:
    """A contradictory unowned marker must not turn an active local lease off.

    A no-persisted-change handoff can leave factory:local and factory:unowned
    together. Visibility enrollment already treats the local lease as active;
    the history sweep must do the same instead of reading unowned as released.
    """
    policy = _policy()
    now = 1_800_000_000

    assert policy.lease_action_for_issue(
        _issue_payload(
            ["factory", "factory:local", "factory:unowned", "factory:building"],
            _iso_timestamp(now - 5),
        ),
        now_epoch=now,
    ) == policy.LEASE_ACTION_HOLD_LOCAL


def test_numbered_lease_is_never_stolen_without_active_run_evidence() -> None:
    """The issue sweep has no fixed-worker evidence, so numbered owners hold."""
    policy = _policy()
    now = 1_800_000_000

    assert policy.lease_action_for_issue(
        _issue_payload(["factory", "factory:7", "factory:building"], _iso_timestamp(now - 10_000)),
        now_epoch=now,
    ) == policy.LEASE_ACTION_HOLD_NUMBERED


def test_numbered_lease_release_requires_authoritative_worker_evidence() -> None:
    """The helper applies the shared fixed-lease TTL only with real evidence."""
    policy = _policy()
    now = 1_800_000_000
    labels = ["factory", "factory:7", "factory:building"]

    assert policy.lease_reconciliation_action(
        labels,
        latest_activity_epoch=now - 901,
        now_epoch=now,
        active_fixed_workers=set(),
        has_unresolved_active_runs=False,
    ) == policy.LEASE_ACTION_RECONCILE
    assert policy.lease_reconciliation_action(
        labels,
        latest_activity_epoch=now - 10_000,
        now_epoch=now,
        active_fixed_workers={7},
        has_unresolved_active_runs=False,
    ) == policy.LEASE_ACTION_HOLD_NUMBERED


def test_conflicting_owners_are_preserved_for_operator_review() -> None:
    """Never guess which of two active owners survives a sweep."""
    policy = _policy()

    assert policy.lease_action_for_issue(
        _issue_payload(["factory", "factory:local", "factory:7"], _iso_timestamp(1_799_999_000)),
        now_epoch=1_800_000_000,
    ) == policy.LEASE_ACTION_HOLD_AMBIGUOUS


def test_released_owner_does_not_block_history_reconciliation() -> None:
    """factory:unowned is a released owner, not a live lease."""
    policy = _policy()

    assert policy.lease_action_for_issue(
        _issue_payload(["factory", "factory:unowned", "factory:review"], None),
        now_epoch=1_800_000_000,
    ) == policy.LEASE_ACTION_RECONCILE


def test_lease_action_cli_reports_hold_for_active_local_lease(tmp_path: Path) -> None:
    """The workflow's real CLI call returns a machine-readable hold."""
    policy = _policy()
    now = 1_800_000_000
    issue_file = tmp_path / "issue.json"
    issue_file.write_text(
        json.dumps(
            _issue_payload(
                ["factory", "factory:local", "factory:building"],
                _iso_timestamp(now - 5),
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(POLICY_SCRIPT),
            "--lease-action-issue-file",
            str(issue_file),
            "--now-epoch",
            str(now),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == policy.LEASE_ACTION_HOLD_LOCAL


def test_reconcile_issue_checks_live_lease_before_replace() -> None:
    """The sweep must pass a freshly read issue through the policy before write."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    body = _reconcile_issue_body(workflow)

    stage_at = body.index('--records-json "$records"')
    guard_at = body.index("--lease-action-issue-file")
    replace_at = body.index('replace_issue_state "$issue" "$stage"')
    assert stage_at < guard_at < replace_at
    assert '[[ "$lease_action" != "reconcile" ]]' in body[guard_at:replace_at]
    assert "return 0" in body[guard_at:replace_at]
    assert body.count('replace_issue_state "$issue" "$stage"') == 1
