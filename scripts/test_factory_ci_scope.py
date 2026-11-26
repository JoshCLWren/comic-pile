"""Factory-only CI may not skip application or pipeline changes."""
import re
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


def _ci_summary_script() -> str:
    """Return the runnable bash body of the real CI Summary step."""
    ci = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text()
    body = ci.split("  check-all-jobs:\n", 1)[1].split("        run: |\n", 1)[1]
    lines: list[str] = []
    for line in body.splitlines():
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line[10:] if line.startswith("          ") else "")
    return "\n".join(lines)


def _render_summary(script: str, fast_only: str, rust_result: str) -> str:
    """Render GitHub expression placeholders in the summary script for a test case."""
    values = {
        "needs.factory-scope.outputs.fast_only": fast_only,
        "needs.native-rust-roll.result": rust_result,
    }
    return re.sub(
        r"\$\{\{\s*([^}]+?)\s*\}\}",
        lambda match: values.get(match.group(1), "success"),
        script,
    )


class RequiredRustGateTests(unittest.TestCase):
    """Regression for #5617: red Native Rust Roll with green CI Summary.

    #5617 merged because Native Rust Roll was a separate optional workflow while
    CI Summary only aggregated its own needs. Rust evidence now runs inside the
    required workflow, so a red suite can no longer be silently ignored.
    """

    def test_native_suite_is_a_required_same_run_dependency(self) -> None:
        """CI Summary must require this run's exact-head Rust suite."""
        # Editing the Rust suite itself must force full CI, not the fast path.
        self.assertFalse(factory_only([".github/workflows/rust-roll.yml"]))
        workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
        ci = (workflows / "ci.yml").read_text()
        rust = (workflows / "rust-roll.yml").read_text()

        caller = ci.split("  native-rust-roll:\n", 1)[1].split("\n  rust-ingress:\n", 1)[0]
        self.assertIn("needs: [factory-scope]", caller)
        self.assertIn("if: needs.factory-scope.outputs.fast_only != 'true'", caller)
        self.assertIn("uses: ./.github/workflows/rust-roll.yml", caller)

        summary = ci.split("  check-all-jobs:\n", 1)[1]
        needs = summary.split("needs: [", 1)[1].split("]", 1)[0]
        self.assertIn("native-rust-roll", needs)
        # A result that is failed, cancelled, skipped, empty (never reported)
        # or from a superseded head is not success and must fail the summary.
        self.assertIn(
            '[ "${{ needs.native-rust-roll.result }}" != "success" ]',
            summary,
        )

        # A reusable same-run call with an exact-head checkout prevents an
        # earlier green run at another SHA from authorizing this candidate.
        self.assertIn("workflow_call:", rust)
        self.assertIn("github.event.pull_request.head.sha || github.sha", rust)
        self.assertIn('git -C "$GITHUB_WORKSPACE" rev-parse HEAD', rust)
        self.assertIn("cargo test --workspace --locked --all-targets", rust)
        # Without this, a standalone pull_request trigger is an optional shadow
        # check that CI Summary can ignore even when it fails.
        self.assertNotIn("  pull_request:\n    paths:", rust)

        # Criterion 5 of #5678: the obsolete Python parity oracle deleted by
        # #5641 must stay gone. Restoring it would mask a real Rust regression
        # behind a stale cross-language comparison.
        parity_oracle = (
            Path(__file__).resolve().parents[1]
            / "native/roll-service/parity/test_http_roll_resources.py"
        )
        self.assertFalse(parity_oracle.exists(), "obsolete parity oracle must not return")

    def test_actual_summary_fails_closed_on_missing_or_red_rust(self) -> None:
        """The real summary shell blocks red, cancelled, skipped and missing Rust."""
        script = _ci_summary_script()
        cases = (
            ("false", "success", 0),
            ("false", "failure", 1),
            ("false", "cancelled", 1),
            ("false", "skipped", 1),
            ("false", "", 1),
            ("true", "skipped", 0),
            ("true", "failure", 0),
        )
        for fast_only, rust_result, expected in cases:
            with self.subTest(fast_only=fast_only, rust_result=rust_result):
                rendered = _render_summary(script, fast_only, rust_result)
                result = subprocess.run(
                    ["bash", "-c", rendered],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
