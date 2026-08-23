"""Regression test for issue #1696: benchmark files must not be tracked."""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_benchmark_result_files_not_tracked():
    """git ls-files benchmarks must return nothing except .gitignore."""
    result = subprocess.run(
        ["git", "ls-files", "benchmarks/"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    files = [line for line in result.stdout.splitlines() if line.strip()]
    # Only the .gitignore file should be tracked
    assert files == ["benchmarks/.gitignore"], f"Unexpected tracked benchmark files: {files}"


def test_benchmark_ignore_rules_exist():
    """benchmarks/.gitignore must ignore results and control-environment dumps."""
    gitignore = REPO_ROOT / "benchmarks" / ".gitignore"
    content = gitignore.read_text(encoding="utf-8")
    assert "results/" in content
    assert "control-environment*.json" in content


def test_makefile_has_mkdir_for_benchmark_targets():
    """Benchmark Makefile targets must create output directories on demand."""
    makefile = REPO_ROOT / "Makefile"
    content = makefile.read_text(encoding="utf-8")
    # Every benchmark-related target should include mkdir -p benchmarks/results
    for target in [
        "railway-control-baseline:",
        "railway-control-results:",
        "railway-control-c32-diagnostic:",
        "railway-control-compare:",
        "railway-control-c32-compare:",
    ]:
        assert target in content, f"Missing target: {target}"
    # Verify mkdir -p appears in the benchmark section
    lines = content.splitlines()
    in_target = False
    for line in lines:
        if "railway-control-baseline:" in line:
            in_target = True
        if in_target and "mkdir -p benchmarks/results" in line:
            break
    else:
        raise AssertionError("Makefile benchmark targets missing mkdir -p benchmarks/results")
