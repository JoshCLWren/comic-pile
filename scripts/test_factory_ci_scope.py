"""Factory-only CI may not skip application or pipeline changes."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_ci_scope import factory_only


class FactoryScopeTests(unittest.TestCase):
    """Verify fast path accepts only factory-infrastructure changes."""
    def test_factory_only_changes(self) -> None:
        """Whitelisted factory code and workflow paths qualify."""
        self.assertTrue(factory_only([
            ".github/workflows/fixed-model-factory-dispatch.yml",
            ".github/workflows/free-model-factory-entry.yml",
            ".github/scripts/factory-work-controller.py",
            "scripts/factory-run",
        ]))
        self.assertTrue(factory_only([".github/workflows/factory-issue-wakeup.yml"]))
        self.assertTrue(factory_only([".github/actions/factory-state-cache/action.yml"]))

    def test_mixed_changes_must_run_full_ci(self) -> None:
        """Application, deployment and policy paths force full CI."""
        for path in (
            "frontend/src/App.tsx", "crates/comicpile/src/lib.rs",
            "migrations/0001.sql", "Cargo.lock", "Dockerfile.ci",
            ".github/workflows/ci.yml", "scripts/factory_ci_scope.py",
            ".github/workflows/deploy-production.yml", "AGENTS.md",
            "scripts/something_factory_important.py", ".github/scripts/auth.py",
            ".github/workflows/factory-service.yml/../ci.yml",
        ):
            with self.subTest(path=path):
                self.assertFalse(factory_only([".github/scripts/factory_opencode_go.py", path]))


    def test_git_rename_from_frontend_to_factory_cannot_use_fast_path(self) -> None:
        """Git move detection must expose both ends of a cross-scope rename."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            old = repo / "frontend/src/App.tsx"
            new = repo / "docs/factory/App.tsx"
            old.parent.mkdir(parents=True)
            old.write_text("export const App = 42;\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run([
                "git", "-C", str(repo), "-c", "user.name=CI",
                "-c", "user.email=ci@example.invalid", "commit", "-qm", "base",
            ], check=True)
            new.parent.mkdir(parents=True)
            old.rename(new)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            paths = subprocess.run([
                "git", "-C", str(repo), "diff", "--cached", "--no-renames",
                "--name-only", "-z",
            ], capture_output=True, check=True).stdout
            names = [part.decode() for part in paths.split(b"\0") if part]
            self.assertEqual(sorted(names), ["docs/factory/App.tsx", "frontend/src/App.tsx"])
            self.assertFalse(factory_only(names))

    def test_empty_and_unsafe(self) -> None:
        """No-diff and directory traversal cases cannot bypass full CI."""
        self.assertFalse(factory_only([]))
        self.assertFalse(factory_only(["../.github/scripts/factory_a.py"]))
        self.assertFalse(factory_only(["/.github/scripts/factory_a.py"]))


if __name__ == "__main__":
    unittest.main()
