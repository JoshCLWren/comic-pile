"""Tests for the repository conflict-marker guard (issue #3491)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Allow importing the script module from scripts/.
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_conflict_markers as guard  # noqa: E402


INCIDENT_8292506_LOCKFILE = """\
packages:

  '@mswjs/interceptors@0.41.9':
    resolution: {integrity: sha512-VVPPgHyQ6ShqnrmDWuxjmUIsO9gWyOZFmuOfLd9LfBGQJwZfy0gvv9pbHSJuoFNIYC7ZDX9aoFwowjcdSC4E8w==}
    engines: {node: '>=18'}

<<<<<<< HEAD
  '@open-draft/deferred-promise@2.2.0':
    resolution: {integrity: sha512-CecwLWx3rhxVQF6V4bAgPS5t+So2sTbPgAzafKkVizyi7tlwpcFpdFqq+wqF2OwNBmqFuu6tOyouTuxgpMfzmA==}
=======
  '@open-draft/deferred-promise@3.0.0':
    resolution: {integrity: sha512-XW375UK8/9SqUVNVa6M0yEy8+iTi4QN5VZ7aZuRFQmy76LRwI9wy5F4YIBU6T+eTe2/DNDo8tqu8RHlwLHM6RA==}
>>>>>>> origin/main

  '@open-draft/logger@0.3.0':
    resolution: {integrity: sha512-X2g45fzhxH238HKO4xbSr7+wBS8Fvw6ixhTDuvLd5mqh6bJJCFAPwU9mPDxbcrRtfxv4u5IHCEH77BmxvXmmxQ==}
<<<<<<< HEAD
  msw:
    specifier: ^2.12.10
    version: 2.15.0
=======
  msw:
    specifier: ^3.0.1
    version: 3.0.2
>>>>>>> origin/main
"""


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_incident_8292506_lockfile_markers_fail_with_file_and_line(tmp_path: Path) -> None:
    """Reproduces commit 8292506: lockfile conflict markers must be reported."""
    write(tmp_path / "frontend/pnpm-lock.yaml", INCIDENT_8292506_LOCKFILE)

    findings = guard.scan_paths(tmp_path, ["frontend/pnpm-lock.yaml"])

    assert findings, "expected conflict markers to be detected"
    rendered = [f.render() for f in findings]
    assert any("frontend/pnpm-lock.yaml:7:" in r and "start marker" in r for r in rendered)
    assert any("frontend/pnpm-lock.yaml:10:" in r and "separator marker" in r for r in rendered)
    assert any("frontend/pnpm-lock.yaml:13:" in r and "end marker" in r for r in rendered)
    # second block
    assert any("frontend/pnpm-lock.yaml:17:" in r and "start marker" in r for r in rendered)
    assert any("frontend/pnpm-lock.yaml:25:" in r and "end marker" in r for r in rendered)
    assert all("frontend/pnpm-lock.yaml" in r for r in rendered)


def test_valid_resolved_pnpm_lock_yaml_passes(tmp_path: Path) -> None:
    """A valid resolved lockfile must not be flagged."""
    resolved = INCIDENT_8292506_LOCKFILE.replace(
        "<<<<<<< HEAD\n"
        "  '@open-draft/deferred-promise@2.2.0':\n"
        "    resolution: {integrity: sha512-CecwLWx3rhxVQF6V4bAgPS5t+So2sTbPgAzafKkVizyi7tlwpcFpdFqq+wqF2OwNBmqFuu6tOyouTuxgpMfzmA==}\n"
        "=======\n"
        "  '@open-draft/deferred-promise@3.0.0':\n"
        "    resolution: {integrity: sha512-XW375UK8/9SqUVNVa6M0yEy8+iTi4QN5VZ7aZuRFQmy76LRwI9wy5F4YIBU6T+eTe2/DNDo8tqu8RHlwLHM6RA==}\n"
        ">>>>>>> origin/main\n",
        "  '@open-draft/deferred-promise@3.0.0':\n"
        "    resolution: {integrity: sha512-XW375UK8/9SqUVNVa6M0yEy8+iTi4QN5VZ7aZuRFQmy76LRwI9wy5F4YIBU6T+eTe2/DNDo8tqu8RHlwLHM6RA==}\n",
    ).replace(
        "<<<<<<< HEAD\n"
        "  msw:\n"
        "    specifier: ^2.12.10\n"
        "    version: 2.15.0\n"
        "=======\n"
        "  msw:\n"
        "    specifier: ^3.0.1\n"
        "    version: 3.0.2\n"
        ">>>>>>> origin/main\n",
        "  msw:\n"
        "    specifier: ^3.0.1\n"
        "    version: 3.0.2\n",
    )
    write(tmp_path / "frontend/pnpm-lock.yaml", resolved)
    assert guard.scan_paths(tmp_path, ["frontend/pnpm-lock.yaml"]) == []


def test_approved_fixture_exclusion_does_not_flag_safe_fixture(tmp_path: Path) -> None:
    """Approved fixture text files may contain deliberate marker examples."""
    fixture = tmp_path / "tests/fixtures/conflict-markers/example.fixture.txt"
    write(
        fixture,
        "<<<<<<< HEAD\nexample\n=======\nother\n>>>>>>> branch\n",
    )
    assert guard.is_approved_fixture_exclusion(
        "tests/fixtures/conflict-markers/example.fixture.txt"
    )
    assert guard.scan_paths(tmp_path, ["tests/fixtures/conflict-markers/example.fixture.txt"]) == []


def test_exclusion_cannot_hide_executable_or_lockfile_conflicts(tmp_path: Path) -> None:
    """Narrow fixture exclusions must not apply to protected/code/lockfile files."""
    protected_paths = [
        "tests/fixtures/conflict-markers/evil.py",
        "tests/fixtures/conflict-markers/evil.js",
        "tests/fixtures/conflict-markers/evil.ts",
        "tests/fixtures/conflict-markers/evil.sh",
        "tests/fixtures/conflict-markers/pnpm-lock.yaml",
        "tests/fixtures/conflict-markers/package-lock.json",
        "tests/fixtures/conflict-markers/config.yaml",
        "tests/fixtures/conflict-markers/data.json",
        "tests/fixtures/conflict-markers/Cargo.lock",
    ]
    marker = "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> branch\n"
    for rel in protected_paths:
        write(tmp_path / rel, marker)
        assert not guard.is_approved_fixture_exclusion(rel), rel
        findings = guard.scan_paths(tmp_path, [rel])
        assert findings, f"protected path must be scanned: {rel}"


def test_multiblock_markers_all_reported(tmp_path: Path) -> None:
    """Multiple conflict blocks in one file are all reported."""
    content = (
        "before\n"
        "<<<<<<< HEAD\none\n=======\ntwo\n>>>>>>> a\n"
        "middle\n"
        "<<<<<<< HEAD\nthree\n=======\nfour\n>>>>>>> b\n"
        "after\n"
    )
    write(tmp_path / "src/file.py", content)
    findings = guard.scan_paths(tmp_path, ["src/file.py"])
    starts = [f for f in findings if "start marker" in f.message]
    ends = [f for f in findings if "end marker" in f.message]
    assert len(starts) == 2
    assert len(ends) == 2


def test_missing_terminator_reported(tmp_path: Path) -> None:
    """An unclosed conflict block is reported as missing terminator."""
    content = "ok\n<<<<<<< HEAD\nleft\n=======\nright\nstill open\n"
    write(tmp_path / "src/broken.py", content)
    findings = guard.scan_paths(tmp_path, ["src/broken.py"])
    assert any("missing end marker" in f.message for f in findings)
    assert any("start marker" in f.message for f in findings)


def test_missing_separator_and_terminator_reported(tmp_path: Path) -> None:
    """A conflict start with no separator/end is reported clearly."""
    write(tmp_path / "a.txt", "<<<<<<< HEAD\nvalue\n")
    findings = guard.scan_paths(tmp_path, ["a.txt"])
    assert any("missing separator and end marker" in f.message for f in findings)


def test_orphan_end_marker_reported(tmp_path: Path) -> None:
    """Orphan end markers are reported."""
    write(tmp_path / "a.py", "ok\n>>>>>>> origin/main\n")
    findings = guard.scan_paths(tmp_path, ["a.py"])
    assert len(findings) == 1
    assert "orphan conflict end marker" in findings[0].message


def test_markdown_setext_heading_not_flagged(tmp_path: Path) -> None:
    """Unrelated ======= separators outside conflict blocks must not be flagged."""
    md = "# Title\n\nHeading\n=======\n\nBody\n"
    write(tmp_path / "README.md", md)
    assert guard.scan_paths(tmp_path, ["README.md"]) == []


def test_exact_head_invalidation(tmp_path: Path) -> None:
    """A clean tree passes; adding markers at the same path fails (head change)."""
    rel = "src/app.py"
    write(tmp_path / rel, "print('ok')\n")
    assert guard.scan_paths(tmp_path, [rel]) == []

    # Simulate a new commit/merge candidate introducing conflict markers.
    write(
        tmp_path / rel,
        "print('ok')\n<<<<<<< HEAD\na\n=======\nb\n>>>>>>> branch\n",
    )
    findings = guard.scan_paths(tmp_path, [rel])
    assert findings, "new head with conflict markers must invalidate prior clean state"


def test_attempted_conflict_containing_merge_checkout(tmp_path: Path) -> None:
    """A synthetic merge checkout tree containing markers fails the gate."""
    # Simulate merge checkout: file contains conflict markers after merge attempt.
    write(tmp_path / "frontend/pnpm-lock.yaml", INCIDENT_8292506_LOCKFILE)
    write(tmp_path / "src/clean.py", "x = 1\n")

    rc = guard.main(["--root", str(tmp_path)])
    assert rc == 1


def test_main_passes_clean_tree(tmp_path: Path) -> None:
    write(tmp_path / "a.py", "print('ok')\n")
    write(tmp_path / "README.md", "Heading\n=======\n\nText\n")
    rc = guard.main(["--root", str(tmp_path)])
    assert rc == 0


def test_binary_files_are_skipped(tmp_path: Path) -> None:
    p = tmp_path / "image.bin"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00\x01<<<<<<< HEAD\n=======\n>>>>>>> x\n")
    assert guard.scan_paths(tmp_path, ["image.bin"]) == []


def test_repo_approved_fixture_file_is_excluded() -> None:
    """The real approved fixture in the repo must be excluded by the guard."""
    repo_root = Path(__file__).resolve().parents[1]
    fixture = "tests/fixtures/conflict-markers/conflict-block.fixture.txt"
    assert (repo_root / fixture).exists()
    assert guard.is_approved_fixture_exclusion(fixture)
    findings = guard.scan_paths(repo_root, [fixture])
    assert findings == []


def test_script_cli_reports_file_and_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path / "bad.yaml", "a: 1\n<<<<<<< HEAD\nb: 2\n=======\nb: 3\n>>>>>>> x\n")
    rc = guard.main(["--root", str(tmp_path), "bad.yaml"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "bad.yaml:2:" in captured.err
    assert "start marker" in captured.err
