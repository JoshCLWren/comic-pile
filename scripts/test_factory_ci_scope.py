"""Factory-only CI may not skip application or pipeline changes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_ci_scope import factory_only


class FactoryScopeTests(unittest.TestCase):
    """Verify fast path accepts only factory-infrastructure changes."""
    def test_factory_only_changes(self):
        """Whitelisted factory code and workflow paths qualify."""
        self.assertTrue(factory_only([
            ".github/workflows/fixed-model-factory-dispatch.yml",
            ".github/workflows/free-model-factory-entry.yml",
            ".github/scripts/factory-work-controller.py",
            "scripts/factory-run",
        ]))
        self.assertTrue(factory_only([".github/workflows/factory-issue-wakeup.yml"]))
        self.assertTrue(factory_only([".github/actions/factory-state-cache/action.yml"]))

    def test_mixed_changes_must_run_full_ci(self):
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

    def test_empty_and_unsafe(self):
        """No-diff and directory traversal cases cannot bypass full CI."""
        self.assertFalse(factory_only([]))
        self.assertFalse(factory_only(["../.github/scripts/factory_a.py"]))
        self.assertFalse(factory_only(["/.github/scripts/factory_a.py"]))


if __name__ == "__main__":
    unittest.main()
