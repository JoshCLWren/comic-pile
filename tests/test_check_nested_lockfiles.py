"""Tests for the nested workspace lockfile CI guard script."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_nested_lockfiles.sh"

LOCKFILE_NAMES = (
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "npm-shrinkwrap.json",
    "bun.lock",
    "bun.lockb",
)


def run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a command in a directory and capture its output."""
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def init_workspace(tmp_path: Path, *, packages: list[str] | None = None) -> Path:
    """Create a minimal git workspace with pnpm-workspace.yaml and the guard script."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    run(["git", "init", "-q"], cwd=repo)
    listed = packages if packages is not None else ["frontend"]
    lines = ["packages:"]
    for pkg in listed:
        lines.append(f"  - '{pkg}'")
    (repo / "pnpm-workspace.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for pkg in listed:
        # create concrete directories for simple package names
        if "*" not in pkg:
            (repo / pkg).mkdir(parents=True, exist_ok=True)
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    target = scripts_dir / "check_nested_lockfiles.sh"
    target.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IEXEC)
    return repo


def test_clean_workspace_passes(tmp_path: Path) -> None:
    """A workspace package with no nested lockfiles passes the guard."""
    repo = init_workspace(tmp_path)
    result = run(["bash", "scripts/check_nested_lockfiles.sh"], cwd=repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No nested lockfiles found in workspace packages." in result.stdout


def test_rejects_each_supported_lockfile_in_workspace_package(tmp_path: Path) -> None:
    """Every supported lockfile name is rejected inside a workspace package."""
    for name in LOCKFILE_NAMES:
        case_dir = tmp_path / name.replace(".", "_")
        repo = init_workspace(case_dir)
        (repo / "frontend" / name).write_text("locked\n", encoding="utf-8")
        result = run(["bash", "scripts/check_nested_lockfiles.sh"], cwd=repo)
        assert result.returncode != 0, (name, result.stdout, result.stderr)
        assert (
            f"ERROR: nested lockfile found in workspace package: frontend/{name}"
            in result.stderr
        )
        assert "Remove it and use the repository root pnpm-lock.yaml." in result.stderr


def test_lockfile_outside_workspace_package_is_allowed(tmp_path: Path) -> None:
    """Lockfiles outside declared workspace packages do not fail the guard."""
    repo = init_workspace(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    result = run(["bash", "scripts/check_nested_lockfiles.sh"], cwd=repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No nested lockfiles found in workspace packages." in result.stdout


def test_missing_workspace_package_directory_is_ignored(tmp_path: Path) -> None:
    """Unmatched workspace package globs or missing directories are ignored."""
    repo = init_workspace(tmp_path, packages=["frontend", "packages/*"])
    result = run(["bash", "scripts/check_nested_lockfiles.sh"], cwd=repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No nested lockfiles found in workspace packages." in result.stdout
