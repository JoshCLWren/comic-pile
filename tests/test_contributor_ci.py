"""Guard fork CI trust boundaries, read-only builds, and summary truthfulness."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RUST_WORKFLOW = ROOT / ".github" / "workflows" / "rust-roll.yml"

BUILD_DEPENDENT_JOBS = (
    "frontend-typecheck",
    "python-lint",
    "python-typecheck",
    "frontend-unit-tests",
    "ui-audit",
)
CONTAINER_BUILD_DEPENDENT_JOBS = (
    "frontend-typecheck",
    "python-lint",
    "python-typecheck",
    "frontend-unit-tests",
)
FULL_PATH_REQUIRED_JOBS = (
    "build",
    "build-fork",
    "native-rust-roll",
    "rust-ingress",
    "route-fragment-guard",
    "conflict-markers",
    "dependency-integrity",
    "docs-code-paths",
    "script-checks",
    "factory-actionlint",
    "factory-shellcheck",
    "native-route-db-test-guard",
    "reading-lists-terminology",
    "frontend-typecheck",
    "python-lint",
    "python-typecheck",
    "frontend-unit-tests",
    "ui-audit",
    "production-runtime-migrations",
    "migration-health",
)


def _workflow(path: Path) -> dict:
    """Load a workflow YAML document from the trusted checkout."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps(job: dict) -> list[dict]:
    """Return the steps of a workflow job."""
    steps = job.get("steps") or []
    assert isinstance(steps, list)
    return steps


def _run_commands(job: dict) -> str:
    """Concatenate the shell commands of a workflow job."""
    return "\n".join(str(step.get("run", "")) for step in _steps(job))


def test_ci_never_runs_fork_code_with_a_privileged_trigger() -> None:
    """CI uses pull_request only, never pull_request_target with a write token."""
    workflow = _workflow(CI_WORKFLOW)
    triggers = workflow.get(True) or workflow.get("on") or {}
    assert "pull_request" in triggers
    assert "pull_request_target" not in triggers
    assert workflow["permissions"] == {"contents": "read"}


def test_fork_build_is_read_only_and_cannot_publish() -> None:
    """Fork code builds without registry credentials; internal publishing remains."""
    jobs = _workflow(CI_WORKFLOW)["jobs"]
    fork = jobs["build-fork"]
    fork_if = str(fork["if"])
    assert "github.event_name == 'pull_request'" in fork_if
    assert "github.event.pull_request.head.repo.full_name != github.repository" in fork_if
    assert fork["permissions"] == {"contents": "read"}
    fork_builds = [
        step
        for step in _steps(fork)
        if "build-push-action" in str(step.get("uses", ""))
    ]
    assert len(fork_builds) == 1
    assert fork_builds[0]["with"]["push"] is False
    serialized_fork = str(fork)
    assert "secrets." not in serialized_fork
    assert "login-action" not in serialized_fork
    assert "packages" not in serialized_fork

    trusted = jobs["build"]
    trusted_if = str(trusted["if"])
    assert "github.event_name != 'pull_request'" in trusted_if
    assert "github.event.pull_request.head.repo.full_name == github.repository" in trusted_if
    assert trusted["permissions"]["packages"] == "write"
    trusted_builds = [
        step
        for step in _steps(trusted)
        if "build-push-action" in str(step.get("uses", ""))
    ]
    assert any(step.get("with", {}).get("push") is True for step in trusted_builds)
    assert "${{ github.sha }}" in str(trusted_builds[0]["with"]["tags"])
    assert any("login-action" in str(step.get("uses", "")) for step in _steps(trusted))


def test_build_trust_boundary_is_repository_event_not_identity() -> None:
    """Trust is derived from the head repository relationship, not author text."""
    jobs = _workflow(CI_WORKFLOW)["jobs"]
    for name in ("build", "build-fork"):
        condition = str(jobs[name]["if"])
        assert "github.event.pull_request.head.repo.full_name" in condition
        assert "github.repository" in condition
        for forbidden in (
            "user.login",
            "github.actor",
            "pull_request.body",
            "pull_request.title",
        ):
            assert forbidden not in condition


@pytest.mark.parametrize("name", BUILD_DEPENDENT_JOBS)
def test_build_dependent_jobs_run_for_a_fork_image(name: str) -> None:
    """Checks gated on the image build still execute for a read-only fork build."""
    job = _workflow(CI_WORKFLOW)["jobs"][name]
    needs = job["needs"]
    assert "build" in needs
    assert "build-fork" in needs
    condition = str(job["if"])
    assert "always()" in condition
    assert "needs.build-fork.result == 'success'" in condition
    checkouts = [
        step
        for step in _steps(job)
        if "actions/checkout" in str(step.get("uses", ""))
    ]
    assert checkouts
    assert all(step.get("with", {}).get("persist-credentials") is False for step in checkouts)


@pytest.mark.parametrize("name", CONTAINER_BUILD_DEPENDENT_JOBS)
def test_fork_container_jobs_install_their_own_toolchain(name: str) -> None:
    """Container jobs never consume the privileged image ref on a fork PR."""
    job = _workflow(CI_WORKFLOW)["jobs"][name]
    image = str(job["container"]["image"])
    assert "needs.build.outputs.image-ref ||" in image
    toolchains = [
        step
        for step in _steps(job)
        if step.get("uses") == "./.github/actions/fork-ci-toolchain"
    ]
    assert len(toolchains) == 1
    toolchain_if = str(toolchains[0]["if"])
    assert "github.event_name == 'pull_request'" in toolchain_if
    assert "head.repo.full_name != github.repository" in toolchain_if


def test_fork_ui_audit_runs_on_an_unprivileged_runner() -> None:
    """The rendered UI audit installs its own dependencies without registry access."""
    job = _workflow(CI_WORKFLOW)["jobs"]["ui-audit"]
    assert job["runs-on"] == "ubuntu-24.04"
    serialized = str(job)
    assert "secrets." not in serialized
    assert "ghcr.io" not in serialized
    commands = _run_commands(job)
    assert "pnpm install --frozen-lockfile" in commands
    assert "playwright install chromium" in commands
    assert "pnpm run audit:ui" in commands


def test_rust_backend_checks_run_on_fork_pull_requests() -> None:
    """Rust unit and integration tests run read-only inside the required CI gate.

    #5678 showed that a standalone pull_request trigger stays visible but can be
    ignored by a green CI Summary. The suite is therefore a reusable workflow
    invoked by ci.yml's native-rust-roll job; fork PRs still get read-only
    permissions, no secrets, and an exact-head checkout.
    """
    workflow = _workflow(RUST_WORKFLOW)
    triggers = workflow.get(True) or workflow.get("on") or {}
    assert "workflow_call" in triggers
    assert "pull_request" not in triggers
    assert "pull_request_target" not in triggers
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["rust-roll"]
    assert "head.repo.full_name" not in str(job.get("if", ""))
    assert "secrets." not in str(job)
    assert "cargo test --workspace --locked --all-targets" in _run_commands(job)
    checkouts = [
        step
        for step in _steps(job)
        if "actions/checkout" in str(step.get("uses", ""))
    ]
    assert checkouts
    assert any(
        "github.event.pull_request.head.sha || github.sha" in str(step.get("with", {}))
        for step in checkouts
    )

    caller = _workflow(CI_WORKFLOW)["jobs"]["native-rust-roll"]
    assert caller["uses"] == "./.github/workflows/rust-roll.yml"
    assert "factory-scope" in caller["needs"]
    assert "fast_only != 'true'" in str(caller["if"])
    assert "secrets." not in str(caller)


def test_ci_summary_covers_every_full_path_job() -> None:
    """A new full-path job cannot go unaccounted for in the CI Summary gate."""
    jobs = set(_workflow(CI_WORKFLOW)["jobs"])
    expected = set(FULL_PATH_REQUIRED_JOBS) | {
        "factory-scope",
        "factory-fast-contracts",
        "check-all-jobs",
    }
    assert jobs == expected


def test_contributor_ci_guards_are_executed_by_ci() -> None:
    """The guard suite itself must gate CI, not just be linted or type-checked."""
    job = _workflow(CI_WORKFLOW)["jobs"]["factory-actionlint"]
    commands = _run_commands(job)
    assert "uv run --frozen python -m pytest" in commands
    assert "tests/test_contributor_ci.py" in commands


@pytest.mark.parametrize("fork", [False, True])
@pytest.mark.parametrize("failed", [None, *FULL_PATH_REQUIRED_JOBS])
def test_ci_summary_requires_real_checks(fork: bool, failed: str | None) -> None:
    """Execute the actual summary shell for each build path and failed gate."""
    jobs = _workflow(CI_WORKFLOW)["jobs"]
    results = dict.fromkeys(jobs["check-all-jobs"]["needs"], "success")
    active_build = "build-fork" if fork else "build"
    inactive_build = "build" if fork else "build-fork"
    results[active_build] = "success"
    results[inactive_build] = "skipped"
    should_fail = failed is not None and failed != inactive_build
    if should_fail:
        assert failed is not None
        results[failed] = "failure"
    shell = str(jobs["check-all-jobs"]["steps"][0]["run"])
    shell = shell.replace("${{ needs.factory-scope.outputs.fast_only }}", "false")
    shell = re.sub(
        r"\$\{\{ needs\.([a-z-]+)\.result }}",
        lambda match: results.get(match[1], "success"),
        shell,
    )
    result = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, check=False)
    assert result.returncode == (1 if should_fail else 0), result.stdout + result.stderr
