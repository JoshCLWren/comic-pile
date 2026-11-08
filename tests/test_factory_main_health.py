"""Regression coverage for the product-only main health signal."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "factory_main_health.py"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SHA = "a" * 40


def load_module() -> ModuleType:
    """Load the main-health helper from its workflow script path.

    Returns:
        Imported helper module.

    """
    spec = importlib.util.spec_from_file_location("factory_main_health", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(
    run_id: int,
    *,
    name: str = "CI",
    event: str = "push",
    head_sha: str = SHA,
    conclusion: str = "success",
) -> dict[str, object]:
    """Build one workflow-run fixture.

    Args:
        run_id: Numeric workflow-run identifier.
        name: Workflow display name.
        event: Triggering GitHub event.
        head_sha: Commit associated with the run.
        conclusion: Terminal workflow conclusion.

    Returns:
        Workflow-run fixture.

    """
    return {
        "conclusion": conclusion,
        "event": event,
        "head_sha": head_sha,
        "id": run_id,
        "name": name,
    }


def test_factory_failures_do_not_mark_product_main_red() -> None:
    """Factory workflow failures cannot contaminate product CI health."""
    module = load_module()
    payload = {
        "workflow_runs": [
            run(
                1,
                name="Fixed Model Factory Entry",
                event="workflow_dispatch",
                conclusion="failure",
            ),
            run(
                2,
                name="Factory Ready Merge Drain",
                event="workflow_dispatch",
                conclusion="failure",
            ),
            run(3),
        ]
    }

    assert module.summarize(payload, SHA) == {
        "failing": 0,
        "failing_names": "",
        "total": 1,
    }


def test_failed_product_ci_marks_main_red_across_pages() -> None:
    """A failed exact-SHA push CI run remains blocking across pagination."""
    module = load_module()
    payload = [
        {"workflow_runs": [run(11), run(12, head_sha="b" * 40, conclusion="failure")]},
        {"workflow_runs": [run(13, conclusion="failure")]},
    ]

    assert module.summarize(payload, SHA) == {
        "failing": 1,
        "failing_names": "CI run 13 (failure)",
        "total": 2,
    }


def test_duplicate_paginated_runs_are_counted_once() -> None:
    """Overlapping REST pages cannot duplicate a main-health failure."""
    module = load_module()
    failed = run(21, conclusion="timed_out")

    assert module.summarize(
        [{"workflow_runs": [failed]}, {"workflow_runs": [failed]}],
        SHA,
    ) == {
        "failing": 1,
        "failing_names": "CI run 21 (timed_out)",
        "total": 1,
    }


def test_all_main_health_gates_use_product_ci_workflow_runs() -> None:
    """Every merge-blocking health gate uses the shared exact-SHA helper."""
    names = (
        "main-health-gate.yml",
        "factory-ready-merge-drain.yml",
        "fixed-model-factory-dispatch.yml",
    )
    for name in names:
        source = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "actions/workflows/ci.yml/runs?head_sha=${sha}&event=push&per_page=100" in source
        assert "gh api --paginate --slurp" in source
        assert "factory_main_health.py --sha \"$sha\"" in source
        assert "commits/${sha}/check-runs?per_page=100" not in source


def test_main_health_gate_only_targets_its_own_issues_and_respects_leases() -> None:
    """Run both real workflow jq selectors against mixed issue fixtures."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required to exercise workflow selectors")

    workflow = (WORKFLOWS / "main-health-gate.yml").read_text(encoding="utf-8")
    opener = workflow.split("      - name: Open or refresh main-breakage P0", 1)[1].split(
        "      - name: Auto-close main-breakage when main is green", 1
    )[0]
    closer = workflow.split("      - name: Auto-close main-breakage when main is green", 1)[1]
    marker = "<!-- comic-pile-main-health-gate:v1 -->"
    assert marker in opener
    assert "--json number,title,body,author,labels" in opener
    assert "--json number,title,body,author,labels" in closer

    def filter_query(section: str) -> str:
        return section.split("--jq '", 1)[1].split("')\"", 1)[0]

    def issue(
        number: int, *, title: str, body: str, author: str = "github-actions[bot]",
        labels: tuple[str, ...] = ("main-breakage", "factory:unowned"),
    ) -> dict[str, object]:
        return {
            "number": number,
            "title": title,
            "body": body,
            "author": {"login": author},
            "labels": [{"name": label} for label in labels],
        }

    legacy = "This issue was opened by Main Health Gate to block the factory"
    fixtures = [
        issue(10, title="Main is red at deadbeef - factory blocked", body=marker,
              author="untrusted-commenter"),
        issue(11, title="Production deploy-fix still pending", body="P0 Rust issue"),
        issue(12, title="Main is red at abcd1234 - factory blocked", body=legacy,
              labels=("main-breakage", "factory:local")),
        issue(13, title="Main is red at efgh1234 - factory blocked", body=legacy),
        issue(14, title="Main CI gate-owned", body=marker,
              labels=("main-breakage", "factory:41")),
        issue(15, title="Main CI gate-owned blocked", body=marker,
              labels=("main-breakage", "factory:blocked")),
        issue(16, title="Main CI gate-owned unclaimed", body=marker),
        issue(17, title="Main CI gate-owned blocked", body=marker,
              labels=("main-breakage", "ralph-status:blocked")),
        issue(18, title="Main CI gate-owned manual", body=marker +
              "\n<!-- factory-execution:manual-only -->"),
    ]

    def selected(section: str) -> list[int]:
        result = subprocess.run(
            [jq, "-r", filter_query(section)], input=json.dumps(fixtures),
            capture_output=True, text=True, check=True,
        )
        return [int(value) for value in result.stdout.splitlines() if value.strip()]

    # A gate-owned lease still blocks duplicate issue creation while main is red.
    assert selected(opener) == [12]
    # Green main may close only gate-owned and unclaimed issues.
    # Neither a spoofed body, unrelated P0, live owner, nor manual hold is touched.
    assert selected(closer) == [13, 16]


def test_held_workflow_recovery_is_unbounded_and_observable() -> None:
    """Held PR workflows remain recoverable after their first hour."""
    drain = (WORKFLOWS / "factory-ready-merge-drain.yml").read_text(encoding="utf-8")
    guard = (WORKFLOWS / "fixed-model-pr-repair-guard.yml").read_text(encoding="utf-8")

    assert "actions/runs?status=action_required&per_page=100" in drain
    assert "gh api --paginate --slurp" in drain
    assert "now - 3600" not in drain
    assert "Approval errors:" in drain
    assert 'gh workflow run "$workflow_file" --ref "$branch"' in drain
    assert "actions/workflows/ci.yml/runs?head_sha=${open_head}&per_page=1" in drain
    assert (
        "actions/workflows/fixed-model-pr-repair-guard.yml/runs?"
        "head_sha=${open_head}&per_page=1"
    ) in drain
    assert "commits/${open_head}/check-runs" not in drain
    assert "workflow_dispatch:" in guard


def test_merge_drain_can_approve_and_dispatch_workflow_recovery() -> None:
    """The drain token has the least privilege needed for Actions recovery."""
    drain = (WORKFLOWS / "factory-ready-merge-drain.yml").read_text(encoding="utf-8")

    permissions = drain.split("permissions:", maxsplit=1)[1].split(
        "concurrency:", maxsplit=1
    )[0]
    assert "actions: write" in permissions
    assert 'GH_TOKEN="$FALLBACK_GH_TOKEN" gh workflow run' in drain
    assert "Dispatch errors for PR #${pr}" in drain
