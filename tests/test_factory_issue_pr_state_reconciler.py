"""Regression coverage for scheduled factory issue-state reconciliation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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
    assert "from factory_work_policy import BLOCKED_LABELS" in policy_source
    assert "set(labels) & BLOCKED_LABELS" in policy_source
