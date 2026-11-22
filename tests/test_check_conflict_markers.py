"""Tests for the repository conflict-marker guard (issue #3491)."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_conflict_markers.py"
SPEC = importlib.util.spec_from_file_location("check_conflict_markers", SCRIPT_PATH)
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


def write(path: Path, content: str) -> None:
    """Write UTF-8 content, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def conflict_block(left: str, right: str, *, end_label: str = "origin/main") -> str:
    """Build a conflict block without embedding markers in this test source."""
    return (
        f"{guard.START_PREFIX} HEAD\n"
        f"{left}\n"
        f"{guard.MID_MARKER}\n"
        f"{right}\n"
        f"{guard.END_PREFIX} {end_label}\n"
    )


MSW_LEFT = (
    "        specifier: ^2.12.10\n"
    "        version: 2.15.0(@types/node@26.6.4)(@typescript/typescript6@6.0.2)"
)
MSW_RIGHT = (
    "        specifier: ^3.0.1\n"
    "        version: 3.0.2(@types/node@26.6.4)(@typescript/typescript6@6.0.2)"
    "(vite@8.3.2(@types/node@26.6.4)(jiti@2.7.0))"
)
VITEST_LEFT = (
    "        version: 5.0.3(@types/node@26.6.4)(@vitest/coverage-v8@5.0.3)"
    "(@vitest/ui@5.0.3)(jsdom@30.1.2)(msw@2.15.0(@types/node@26.6.4)"
    "(@typescript/typescript6@6.0.2))(vite@8.3.2(@types/node@26.6.4)(jiti@2.7.0))"
)
VITEST_RIGHT = (
    "        version: 5.0.3(@types/node@26.6.4)(@vitest/coverage-v8@5.0.3)"
    "(@vitest/ui@5.0.3)(jsdom@30.1.2)(msw@3.0.2(@types/node@26.6.4)"
    "(@typescript/typescript6@6.0.2)(vite@8.3.2(@types/node@26.6.4)(jiti@2.7.0)))"
    "(vite@8.3.2(@types/node@26.6.4)(jiti@2.7.0))"
)
MSW_CONFLICT = conflict_block(MSW_LEFT, MSW_RIGHT)
VITEST_CONFLICT = conflict_block(VITEST_LEFT, VITEST_RIGHT)
INCIDENT_8292506_LOCKFILE = (
    "importers:\n\n"
    "  .:\n"
    "    devDependencies:\n"
    "      msw:\n"
    f"{MSW_CONFLICT}"
    "      vitest:\n"
    "        specifier: ^5.0.3\n"
    f"{VITEST_CONFLICT}"
)
RESOLVED_8292506_LOCKFILE = INCIDENT_8292506_LOCKFILE.replace(
    MSW_CONFLICT,
    f"{MSW_RIGHT}\n",
).replace(VITEST_CONFLICT, f"{VITEST_RIGHT}\n")


def run_guard(root: Path, *paths: str) -> tuple[int, str, str]:
    """Run the real CLI and capture its exit code and output streams."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = guard.main(["--root", str(root), *paths])
    return result, stdout.getvalue(), stderr.getvalue()


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run Git in a disposable test repository."""
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def init_repository(root: Path) -> None:
    """Initialize a disposable Git repository with a deterministic identity."""
    git(root, "init", "--quiet", "--initial-branch=main")
    git(root, "config", "user.name", "Conflict Guard Test")
    git(root, "config", "user.email", "conflict-guard@example.invalid")


def commit_all(root: Path, message: str) -> str:
    """Commit every file in a disposable repository and return its head SHA."""
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", message)
    return git(root, "rev-parse", "HEAD").stdout.strip()


class ConflictMarkerGuardTests(unittest.TestCase):
    """Exercise marker detection and its required CI integration."""

    def temporary_root(self) -> Path:
        """Create an isolated directory cleaned up after the test."""
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        return Path(temporary_directory.name)

    def test_incident_8292506_lockfile_markers_fail_with_file_and_line(self) -> None:
        """The historical msw/vitest lockfile conflicts fail with precise locations."""
        root = self.temporary_root()
        write(root / "frontend/pnpm-lock.yaml", INCIDENT_8292506_LOCKFILE)

        result, _, stderr = run_guard(root, "frontend/pnpm-lock.yaml")

        self.assertEqual(result, 1)
        for line, marker in (
            (6, "start marker"),
            (9, "separator marker"),
            (12, "end marker"),
            (15, "start marker"),
            (17, "separator marker"),
            (19, "end marker"),
        ):
            with self.subTest(line=line, marker=marker):
                self.assertIn(f"frontend/pnpm-lock.yaml:{line}:", stderr)
                self.assertIn(marker, stderr)

    def test_valid_resolved_pnpm_lock_yaml_passes(self) -> None:
        """The incident lockfile passes after selecting the resolved right-hand sides."""
        root = self.temporary_root()
        write(root / "frontend/pnpm-lock.yaml", RESOLVED_8292506_LOCKFILE)
        self.assertNotIn(guard.START_PREFIX, RESOLVED_8292506_LOCKFILE)
        self.assertNotIn(guard.END_PREFIX, RESOLVED_8292506_LOCKFILE)

        result, stdout, stderr = run_guard(root, "frontend/pnpm-lock.yaml")

        self.assertEqual(result, 0, stderr)
        self.assertIn("No unresolved Git conflict markers", stdout)

    def test_repository_pnpm_lockfile_is_clean(self) -> None:
        """The actual resolved repository lockfile passes the same production gate."""
        result, _, stderr = run_guard(ROOT, "frontend/pnpm-lock.yaml")
        self.assertEqual(result, 0, stderr)

    def test_approved_fixture_exclusion_does_not_flag_safe_fixture(self) -> None:
        """Approved fixture text files may contain deliberate marker examples."""
        root = self.temporary_root()
        relative = "tests/fixtures/conflict-markers/example.fixture.txt"
        write(root / relative, conflict_block("example", "other", end_label="branch"))

        self.assertTrue(guard.is_approved_fixture_exclusion(relative))
        self.assertEqual(guard.scan_paths(root, [relative]), [])

    def test_exclusion_cannot_hide_executable_or_lockfile_conflicts(self) -> None:
        """Narrow fixture exclusions never apply to code or structured-data files."""
        root = self.temporary_root()
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
        marker = conflict_block("a", "b", end_label="branch")
        for relative in protected_paths:
            with self.subTest(relative=relative):
                write(root / relative, marker)
                self.assertFalse(guard.is_approved_fixture_exclusion(relative))
                self.assertTrue(guard.scan_paths(root, [relative]))

    def test_multiblock_markers_all_reported(self) -> None:
        """Multiple conflict blocks in one file are all reported."""
        root = self.temporary_root()
        content = (
            "before\n"
            + conflict_block("one", "two", end_label="a")
            + "middle\n"
            + conflict_block("three", "four", end_label="b")
            + "after\n"
        )
        write(root / "src/file.py", content)

        findings = guard.scan_paths(root, ["src/file.py"])

        starts = [finding for finding in findings if "start marker" in finding.message]
        ends = [finding for finding in findings if "end marker" in finding.message]
        self.assertEqual(len(starts), 2)
        self.assertEqual(len(ends), 2)

    def test_missing_terminator_reported(self) -> None:
        """An unclosed conflict block is reported as missing its terminator."""
        root = self.temporary_root()
        content = f"ok\n{guard.START_PREFIX} HEAD\nleft\n{guard.MID_MARKER}\nright\nstill open\n"
        write(root / "src/broken.py", content)

        findings = guard.scan_paths(root, ["src/broken.py"])

        self.assertTrue(any("missing end marker" in finding.message for finding in findings))
        self.assertTrue(any("start marker" in finding.message for finding in findings))

    def test_missing_separator_and_terminator_reported(self) -> None:
        """A conflict start with no separator or end is reported clearly."""
        root = self.temporary_root()
        write(root / "a.txt", f"{guard.START_PREFIX} HEAD\nvalue\n")

        findings = guard.scan_paths(root, ["a.txt"])

        self.assertTrue(
            any("missing separator and end marker" in finding.message for finding in findings)
        )

    def test_orphan_end_marker_reported(self) -> None:
        """Orphan end markers are reported rather than mistaken for prose."""
        root = self.temporary_root()
        write(root / "a.py", f"ok\n{guard.END_PREFIX} origin/main\n")

        findings = guard.scan_paths(root, ["a.py"])

        self.assertEqual(len(findings), 1)
        self.assertIn("orphan conflict end marker", findings[0].message)

    def test_markdown_setext_heading_not_flagged(self) -> None:
        """Unrelated seven-equals separators outside conflict blocks are not flagged."""
        root = self.temporary_root()
        write(root / "README.md", "# Title\n\nHeading\n=======\n\nBody\n")
        self.assertEqual(guard.scan_paths(root, ["README.md"]), [])

    def test_exact_head_invalidation(self) -> None:
        """A new commit cannot reuse the clean result from its parent commit."""
        root = self.temporary_root()
        init_repository(root)
        relative = "src/app.py"
        write(root / relative, "print('ok')\n")
        clean_head = commit_all(root, "clean candidate")
        clean_result, _, clean_stderr = run_guard(root)
        self.assertEqual(clean_result, 0, clean_stderr)

        write(root / relative, "print('ok')\n" + conflict_block("a", "b", end_label="branch"))
        conflicted_head = commit_all(root, "conflicted candidate")
        conflicted_result, _, conflicted_stderr = run_guard(root)

        self.assertNotEqual(conflicted_head, clean_head)
        self.assertEqual(conflicted_result, 1)
        self.assertIn("src/app.py:2:", conflicted_stderr)

    def test_attempted_conflict_containing_merge_checkout(self) -> None:
        """A real Git merge attempt with lockfile conflicts fails the gate."""
        root = self.temporary_root()
        init_repository(root)
        relative = "frontend/pnpm-lock.yaml"
        write(root / relative, "importers:\n  .:\n    msw: base\n")
        commit_all(root, "base lockfile")
        git(root, "checkout", "--quiet", "-b", "candidate")
        write(root / relative, "importers:\n  .:\n    msw: candidate\n")
        commit_all(root, "candidate lockfile")
        git(root, "checkout", "--quiet", "main")
        write(root / relative, "importers:\n  .:\n    msw: main\n")
        commit_all(root, "main lockfile")

        merge = git(root, "merge", "candidate", check=False)
        result, _, stderr = run_guard(root)

        self.assertNotEqual(merge.returncode, 0)
        self.assertIn(guard.START_PREFIX, (root / relative).read_text(encoding="utf-8"))
        self.assertEqual(result, 1)
        self.assertIn("frontend/pnpm-lock.yaml:3:", stderr)
        self.assertEqual(stderr.count("unresolved conflict start marker"), 1)

    def test_main_passes_clean_tree(self) -> None:
        """A clean tree with ordinary Markdown separators exits successfully."""
        root = self.temporary_root()
        write(root / "a.py", "print('ok')\n")
        write(root / "README.md", "Heading\n=======\n\nText\n")
        result, _, stderr = run_guard(root)
        self.assertEqual(result, 0, stderr)

    def test_binary_files_are_skipped(self) -> None:
        """Binary files are skipped even if they contain marker-like bytes."""
        root = self.temporary_root()
        path = root / "image.bin"
        path.write_bytes(b"\x00\x01<<<<<<< HEAD\n=======\n>>>>>>> x\n")
        self.assertEqual(guard.scan_paths(root, ["image.bin"]), [])

    def test_repo_approved_fixture_file_is_excluded(self) -> None:
        """The real approved fixture is excluded while the rest of the tree is scanned."""
        relative = "tests/fixtures/conflict-markers/conflict-block.fixture.txt"
        self.assertTrue((ROOT / relative).exists())
        self.assertTrue(guard.is_approved_fixture_exclusion(relative))
        self.assertEqual(guard.scan_paths(ROOT, [relative]), [])

    def test_script_cli_reports_file_and_line(self) -> None:
        """CLI output identifies the file and line for each finding."""
        root = self.temporary_root()
        content = "a: 1\n" + conflict_block("b: 2", "b: 3", end_label="x")
        write(root / "bad.yaml", content)

        result, _, stderr = run_guard(root, "bad.yaml")

        self.assertEqual(result, 1)
        self.assertIn("bad.yaml:2:", stderr)
        self.assertIn("start marker", stderr)

    def test_required_ci_scans_head_and_merge_candidate(self) -> None:
        """The required summary gates both checkout content and the exact PR head."""
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        summary = workflow.split("  check-all-jobs:\n", 1)[1]
        needs_line = next(line for line in summary.splitlines() if "needs:" in line)

        self.assertIn("  conflict-markers:\n", workflow)
        self.assertIn("conflict-markers", needs_line)
        self.assertIn('"${{ needs.conflict-markers.result }}"', summary)
        self.assertIn('[ "${{ needs.conflict-markers.result }}" != "success" ]', summary)
        self.assertIn("python3 scripts/check_conflict_markers.py\n", workflow)
        self.assertIn('git archive "$HEAD_SHA"', workflow)
        self.assertIn(
            'python3 scripts/check_conflict_markers.py --root "$head_tree"',
            workflow,
        )
        self.assertIn(
            "python3 -m unittest discover -s tests -p test_check_conflict_markers.py",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
