"""Comic Pile's side of the Rotisserie factory contract.

The factory code and its tests live in JoshCLWren/rotisserie. These checks cover
what stays in this repository: app workflows the factory relies on, the
installed factory workflows, and the adopter configuration.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RUNTIME_STEP = "rotisserie-factory-runtime"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _installed_workflows() -> list[Path]:
    return sorted(
        path for path in WORKFLOWS.glob("*.yml") if RUNTIME_STEP in path.read_text(encoding="utf-8")
    )


def test_deploy_production_dedupes_factory_dispatches_and_serializes_runs() -> None:
    """Factory merges dispatch Deploy Production; manual runs stay distinguishable."""
    text = (WORKFLOWS / "deploy-production.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = workflow[True] if True in workflow else workflow["on"]
    source = triggers["workflow_dispatch"]["inputs"]["source"]
    assert source["default"] == "manual"
    assert source["type"] == "choice"
    assert {"manual", "factory-merge"} <= set(source["options"])
    run_name = workflow["run-name"]
    assert "inputs.source" in run_name and "inputs.reason" in run_name
    assert "Deploy Production [source={0}]" in run_name
    assert workflow["concurrency"] == {"group": "vercel-production", "cancel-in-progress": False}
    assert "DISPATCH_SOURCE: ${{ github.event.inputs.source || 'manual' }}" in text
    assert (
        '"$GITHUB_EVENT_NAME" == "workflow_dispatch" && "$DISPATCH_SOURCE" != "factory-merge"'
        in text
    )
    preflight = workflow["jobs"]["preflight"]
    assert preflight["steps"][0]["with"]["ref"] == "main"


def test_revision_is_published_before_preflight_dependencies() -> None:
    """A selected checkout remains attributable even when setup/preflight fails."""
    deploy = (WORKFLOWS / "deploy-production.yml").read_text(encoding="utf-8")
    preflight = deploy.split("  preflight:")[1].split("  deploy:")[0]
    assert preflight.index("Publish selected deployment revision") < preflight.index(
        "Require Vercel token"
    )
    assert "deployment-attempt-${{ github.run_attempt }}" in preflight
    assert "run_attempt: $run_attempt" in preflight
    assert "steps.revision.outputs.deploy_sha" in preflight


def test_recovery_workflow_uses_trusted_main_and_heartbeat() -> None:
    """Repair reconciliation runs on failures and latched freezes without secrets."""
    workflow = (WORKFLOWS / "production-deploy-recovery.yml").read_text(encoding="utf-8")
    assert "workflows: [Deploy Production]" in workflow
    assert "cron:" in workflow
    assert "ref: main" in workflow
    assert "secrets." not in workflow
    deploy = (WORKFLOWS / "deploy-production.yml").read_text(encoding="utf-8")
    assert "--build-env COMICPILE_BUILD_SHA=" in deploy
    assert ".build.revision == $sha" in deploy


def test_main_health_reporting_does_not_create_tickets() -> None:
    """Main health stays an observable CI signal, never a backlog producer."""
    gate = (WORKFLOWS / "main-health-gate.yml").read_text(encoding="utf-8")
    dispatcher = (WORKFLOWS / "fixed-model-factory-dispatch.yml").read_text(encoding="utf-8")
    assert "workflow_run:" in gate
    assert "types: [completed]" in gate
    assert "github.event.workflow_run.conclusion" in gate
    assert "issues: write" not in gate
    assert "gh issue create" not in gate
    assert "gh issue close" not in gate
    assert "Open or refresh main-breakage" not in gate
    assert "Auto-close main-breakage" not in gate
    assert "gh issue create" not in dispatcher
    assert "main-breakage" not in dispatcher
    assert "main_red=true" in dispatcher
    assert "drain will pause merges" in dispatcher


def test_pr_ci_cancels_superseded_heads_without_canceling_main() -> None:
    """PR CI cancels stale heads while main-branch CI stays non-canceling."""
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert (
        "group: ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}"
        in ci
    )
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in ci


def test_ci_summary_keeps_workflow_and_shell_gates_without_factory_tests() -> None:
    """Factory tests run in Rotisserie; Comic Pile CI still lints every workflow and script."""
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    summary = yaml.safe_load(ci)["jobs"]["check-all-jobs"]
    assert {"script-checks", "factory-actionlint", "factory-shellcheck"} <= set(summary["needs"])
    assert "factory-complete-tests" not in ci
    assert "test_factory_" not in ci
    assert "factory-fast-merge-wakeup:" not in ci
    assert "actions: write" not in ci


def test_installed_factory_workflows_pin_one_rotisserie_commit() -> None:
    """Every installed workflow runs the same exact Rotisserie commit, without secrets."""
    installed = _installed_workflows()
    assert installed
    refs = set()
    for path in installed:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in (workflow.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                options = step.get("with") or {}
                if options.get("repository") == "JoshCLWren/rotisserie" and "runtime" in str(
                    options.get("path", "")
                ):
                    refs.add(options["ref"])
                    assert options["persist-credentials"] is False, path.name
                    assert "ssh-key" not in options, path.name
    assert len(refs) == 1
    assert SHA_RE.match(refs.pop())


def test_factory_code_is_not_tracked_here() -> None:
    """Factory scripts and tests belong to Rotisserie; a tracked copy blocks the overlay."""
    tracked = subprocess.run(
        ["git", "ls-files", ".github/scripts", "tests", "scripts", ".agents/skills"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    factory = [
        path
        for path in tracked
        if re.search(r"(^|/)(test_)?factory[_-]", path)
        or path.startswith((".agents/skills/local-factory-", ".agents/skills/crouton-factory-"))
    ]
    assert factory == []


def test_adopter_config_names_this_repository() -> None:
    """The adopter config keeps this repository and its existing marker namespace."""
    config = tomllib.loads((ROOT / ".rotisserie" / "config.toml").read_text(encoding="utf-8"))
    assert config["repository"] == {
        "host": "github.com",
        "owner": "JoshCLWren",
        "name": "comic-pile",
    }
    assert config["markers"]["namespace"] == "comic-pile-factory"
