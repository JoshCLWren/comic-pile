"""Regression tests for the repository pre-commit Rust formatting hook."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRE_COMMIT = ROOT / ".githooks" / "pre-commit"
FORMATTED_RUST = 'fn main() {\n    println!("ok");\n}\n'
UNFORMATTED_RUST = 'fn main(){println!("ok");}\n'


def git(repository: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run Git in a disposable test repository."""
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=check,
        capture_output=True,
        text=True,
    )


class PreCommitRustFormattingTests(unittest.TestCase):
    """Verify the hook never formats content different from the staged blob."""

    def setUp(self) -> None:
        """Create an isolated repository with no-op lint and rustfmt commands."""
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.repository = Path(temporary_directory.name)
        self.rustfmt_calls = self.repository / "rustfmt-calls"

        git(self.repository, "init", "--quiet", "--initial-branch=main")
        git(self.repository, "config", "user.name", "Hook Test")
        git(self.repository, "config", "user.email", "hook-test@example.invalid")
        (self.repository / "README.md").write_text("seed\n", encoding="utf-8")
        git(self.repository, "add", "README.md")
        git(self.repository, "commit", "--quiet", "-m", "seed")

        (self.repository / ".githooks").mkdir()
        shutil.copy2(PRE_COMMIT, self.repository / ".githooks" / "pre-commit")
        (self.repository / "scripts").mkdir()
        (self.repository / "scripts" / "lint.sh").write_text(
            "#!/usr/bin/env bash\nexit 0\n",
            encoding="utf-8",
        )
        (self.repository / "pyproject.toml").write_text("", encoding="utf-8")
        (self.repository / "src").mkdir()
        self.rust_file = self.repository / "src" / "lib.rs"

        binaries = self.repository / "bin"
        binaries.mkdir()
        rustfmt = binaries / "rustfmt"
        rustfmt.write_text(
            '#!/usr/bin/env bash\nprintf "called\\n" >> "$RUSTFMT_CALLS"\nexit 0\n',
            encoding="utf-8",
        )
        rustfmt.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment["PATH"] = f"{binaries}{os.pathsep}{self.environment['PATH']}"
        self.environment["RUSTFMT_CALLS"] = str(self.rustfmt_calls)

    def stage_rust(self, staged: str, unstaged: str) -> str:
        """Stage one Rust version, then replace the working tree with another."""
        self.rust_file.write_text(staged, encoding="utf-8")
        git(self.repository, "add", "src/lib.rs")
        self.rust_file.write_text(unstaged, encoding="utf-8")
        return git(self.repository, "show", ":src/lib.rs").stdout

    def run_hook(self) -> subprocess.CompletedProcess[str]:
        """Run the real pre-commit hook in the disposable repository."""
        return subprocess.run(
            ["bash", ".githooks/pre-commit"],
            cwd=self.repository,
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_mixed_state_rejected(self, staged: str, unstaged: str) -> None:
        """Mixed content must fail without changing either copy or calling rustfmt."""
        staged_blob = self.stage_rust(staged, unstaged)

        result = self.run_hook()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("has both staged and unstaged changes", result.stdout)
        self.assertEqual(git(self.repository, "show", ":src/lib.rs").stdout, staged_blob)
        self.assertEqual(self.rust_file.read_text(encoding="utf-8"), unstaged)
        self.assertFalse(self.rustfmt_calls.exists())

    def test_unformatted_staged_rust_with_formatted_worktree_is_rejected(self) -> None:
        """An unformatted staged blob must fail even when the worktree is formatted."""
        self.assert_mixed_state_rejected(UNFORMATTED_RUST, FORMATTED_RUST)

    def test_formatted_staged_rust_with_unformatted_worktree_reports_mixed_state(self) -> None:
        """Unstaged content must not be mistaken for unformatted staged content."""
        self.assert_mixed_state_rejected(FORMATTED_RUST, UNFORMATTED_RUST)


if __name__ == "__main__":
    unittest.main()
