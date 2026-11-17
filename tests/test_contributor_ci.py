"""Guard fork CI permissions, test execution, and summary truthfulness."""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_fork_build_is_read_only_and_cannot_publish() -> None:
    """Fork code builds without registry credentials; internal publishing remains."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    fork = jobs["build-fork"]
    assert fork["permissions"] == {"contents": "read"}
    assert "head.repo.full_name != github.repository" in fork["if"]
    build = next(step for step in fork["steps"] if "build-push-action" in step.get("uses", ""))
    assert build["with"]["push"] is False
    assert "secrets." not in str(fork)
    assert "login-action" not in str(fork)
    trusted = jobs["build"]
    assert "head.repo.full_name == github.repository" in trusted["if"]
    assert trusted["permissions"]["packages"] == "write"
    assert any(step.get("with", {}).get("push") is True for step in trusted["steps"])
    # The Rust cutover retired legacy Python suite/coverage jobs.
    assert "coverage-gate" not in jobs
    assert "test-unit" not in jobs
    for name in (
        "frontend-typecheck", "python-lint", "python-typecheck",
        "frontend-unit-tests", "migration-health", "ui-audit",
    ):
        job = jobs[name]
        expected_needs = ["build", "build-fork"]
        if name in ("ui-audit", "frontend-unit-tests"):
            expected_needs.append("rust-ingress")
            assert "needs.rust-ingress.result == 'success'" in job["if"]
        if name == "ui-audit":
            assert job["runs-on"] == "ubuntu-24.04"
        assert job["needs"] == expected_needs
        assert "always()" in job["if"]
        assert "needs.build-fork.result == 'success'" in job["if"]
        if name != "ui-audit":
            assert "python:3.14-trixie" in job["container"]["image"]
            assert any(
                step.get("uses") == "./.github/actions/fork-ci-toolchain"
                for step in job["steps"]
            )


@pytest.mark.parametrize("fork", [False, True])
@pytest.mark.parametrize(
    "failed",
    [None] + yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"][
        "check-all-jobs"
    ]["needs"],
)
def test_ci_summary_requires_real_checks(fork: bool, failed: str | None) -> None:
    """Execute the actual summary shell for each build path and failed gate."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    results = dict.fromkeys(jobs["check-all-jobs"]["needs"], "success")
    results["build" if fork else "build-fork"] = "skipped"
    if failed in ("build", "build-fork"):
        results["build-fork" if fork else "build"] = "failure"
    elif failed:
        results[failed] = "failure"
    shell = jobs["check-all-jobs"]["steps"][0]["run"]
    shell = re.sub(
        r"\$\{\{ needs\.([a-z-]+)\.result }}",
        lambda match: results[match[1]], shell,
    )
    result = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, check=False)
    assert result.returncode == (0 if failed is None else 1), result.stdout + result.stderr
