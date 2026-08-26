"""Regression contract for issue #1696: benchmark output snapshots stay untracked."""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _tracked_files(pathspec: str) -> list[str]:
    """Return tracked files under pathspec, failing loudly when git cannot run."""
    result = subprocess.run(
        # CI job containers run as root over a host-owned checkout; without the
        # safe.directory override git refuses to operate and prints nothing.
        ["git", "-c", f"safe.directory={REPO_ROOT}", "ls-files", pathspec],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, (
        f"git ls-files {pathspec} exited {result.returncode}: {result.stderr}"
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_benchmark_result_files_not_tracked():
    """Git must track no files under benchmarks/ on a clean checkout."""
    assert _tracked_files("benchmarks/") == [], "Benchmark files must not be tracked"


def test_benchmark_ignore_rules_exist():
    """Root .gitignore must ignore benchmark results and environment dumps."""
    content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "benchmarks/results/" in content
    assert "benchmarks/control-environment*.json" in content


def test_makefile_has_mkdir_for_benchmark_targets():
    """Benchmark Makefile targets must create the output directory on demand."""
    makefile = REPO_ROOT / "Makefile"
    lines = makefile.read_text(encoding="utf-8").splitlines()
    for target in [
        "railway-control-baseline:",
        "railway-control-results:",
        "railway-control-c32-diagnostic:",
        "railway-control-compare:",
        "railway-control-c32-compare:",
    ]:
        index = next(
            (i for i, line in enumerate(lines) if line.startswith(target)), None
        )
        assert index is not None, f"Missing target: {target}"
        recipe = lines[index + 1]
        assert "mkdir -p benchmarks/results" in recipe, (
            f"Target {target} must create benchmarks/results before writing outputs"
        )
