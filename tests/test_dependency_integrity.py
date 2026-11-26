"""Tests for the pnpm dependency-integrity guard and its required CI gate (issue #3494)."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_dependency_integrity.py"
SPEC = importlib.util.spec_from_file_location("check_dependency_integrity", SCRIPT_PATH)
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)

ROOT_MANIFEST = {
    "name": "comic-pile",
    "private": True,
    "packageManager": "pnpm@10.15.0+sha512.486ebc259d3e999a4e8691ce03b5cac4a71cbeca39372a9b762cb500cfdf0873e2cb16abe3d951b1ee2cf012503f027b98b6584e4df22524e0c7450d9ec7aa7b",
    "dependencies": {"dotenv": "^18.0.10"},
    "devDependencies": {"vitest": "^5.1.1"},
}
FRONTEND_MANIFEST = {
    "name": "frontend",
    "private": True,
    "dependencies": {"react": "^19.3.1"},
    "devDependencies": {"msw": "^3.0.7"},
}
WORKSPACE = "packages:\n  - 'frontend'\n"
DOCKERFILE = "FROM base\nRUN npm install -g pnpm@10.15.0\n"
LOCKFILE = """lockfileVersion: '9.0'

settings:
  autoInstallPeers: true

importers:

  .:
    dependencies:
      dotenv:
        specifier: ^18.0.10
        version: 18.0.10
    devDependencies:
      vitest:
        specifier: ^5.1.1
        version: 5.1.1

  frontend:
    dependencies:
      react:
        specifier: ^19.3.1
        version: 19.3.1
    devDependencies:
      msw:
        specifier: ^3.0.7
        version: 3.0.7

packages: {}

snapshots: {}
"""


def write(path: Path, content: str) -> None:
    """Write UTF-8 content, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, data: dict[str, object]) -> None:
    """Write formatted JSON with a trailing newline."""
    write(path, json.dumps(data, indent=2) + "\n")


def conflict_block(left: str, right: str, *, end_label: str = "origin/main") -> str:
    """Build a conflict block without embedding markers in test source."""
    return (
        f"{guard.START_MARKER} HEAD\n"
        f"{left}\n"
        f"{guard.MID_MARKER}\n"
        f"{right}\n"
        f"{guard.END_MARKER} {end_label}\n"
    )


MSW_CONFLICT = conflict_block(
    "        specifier: ^2.12.10\n"
    "        version: 2.15.0(@types/node@26.6.4)(@typescript/typescript6@6.0.2)",
    "        specifier: ^3.0.1\n"
    "        version: 3.0.2(@types/node@26.6.4)(@typescript/typescript6@6.0.2)",
)
VITEST_CONFLICT = conflict_block(
    "        version: 5.0.3(@types/node@26.6.4)(msw@2.15.0)",
    "        version: 5.0.3(@types/node@26.6.4)(msw@3.0.2)",
)
HISTORICAL_NESTED_LOCKFILE = (
    "importers:\n\n"
    "  .:\n"
    "    devDependencies:\n"
    "      msw:\n"
    f"{MSW_CONFLICT}"
    "      vitest:\n"
    "        specifier: ^5.0.3\n"
    f"{VITEST_CONFLICT}"
)


def make_valid_repo(root: Path) -> None:
    """Create a minimal valid root + frontend pnpm workspace candidate tree."""
    write_json(root / "package.json", ROOT_MANIFEST)
    write(root / "pnpm-workspace.yaml", WORKSPACE)
    write(root / "Dockerfile.ci", DOCKERFILE)
    write(root / "pnpm-lock.yaml", LOCKFILE)
    write_json(root / "frontend/package.json", FRONTEND_MANIFEST)


def run_guard(root: Path) -> tuple[int, str, str]:
    """Run the real CLI and capture exit code and output streams."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = guard.main(["--root", str(root)])
    return result, stdout.getvalue(), stderr.getvalue()


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run Git in a disposable candidate repository."""
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def commit_all(root: Path, message: str) -> str:
    """Commit every file and return the resulting exact head SHA."""
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", message)
    return git(root, "rev-parse", "HEAD").stdout.strip()


class DependencyIntegrityGuardTests(unittest.TestCase):
    """Exercise offline dependency validation and its exact-head CI integration."""

    def temporary_root(self) -> Path:
        """Create an isolated directory cleaned up after the test."""
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        return Path(temporary_directory.name)

    def test_current_repository_is_valid(self) -> None:
        """The real root and frontend workspace files pass the production guard."""
        result, _, stderr = run_guard(ROOT)

        self.assertEqual(result, 0, stderr)

    def test_historical_nested_conflict_lockfile_fails_for_correct_reason(self) -> None:
        """The historical msw/vitest blocks fail even though pnpm reads the root lockfile."""
        root = self.temporary_root()
        make_valid_repo(root)
        write(root / "frontend/pnpm-lock.yaml", HISTORICAL_NESTED_LOCKFILE)

        result, _, stderr = run_guard(root)

        self.assertEqual(result, 1)
        self.assertIn("frontend/pnpm-lock.yaml: nested lockfile", stderr)
        self.assertIn("frontend/pnpm-lock.yaml:5: unresolved Git conflict marker", stderr)
        self.assertIn("frontend/pnpm-lock.yaml:8: unresolved Git conflict marker", stderr)
        self.assertIn("frontend/pnpm-lock.yaml:11: unresolved Git conflict marker", stderr)

    def test_valid_dependency_update_passes(self) -> None:
        """A coherent frontend manifest/lockfile version bump passes without manual intervention."""
        root = self.temporary_root()
        make_valid_repo(root)
        manifest = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
        manifest["devDependencies"]["msw"] = "^3.0.8"
        write_json(root / "frontend/package.json", manifest)
        write(
            root / "pnpm-lock.yaml",
            LOCKFILE.replace("specifier: ^3.0.7", "specifier: ^3.0.8")
            .replace("version: 3.0.7", "version: 3.0.8"),
        )

        result, _, stderr = run_guard(root)

        self.assertEqual(result, 0, stderr)

    def test_manifest_lockfile_specifier_mismatch_fails(self) -> None:
        """A manifest changed without its lockfile fails with the exact range difference."""
        root = self.temporary_root()
        make_valid_repo(root)
        manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
        manifest["dependencies"]["dotenv"] = "^19.0.0"
        write_json(root / "package.json", manifest)

        result, _, stderr = run_guard(root)

        self.assertEqual(result, 1)
        self.assertIn(". dependencies.dotenv specifier '^18.0.10' != manifest '^19.0.0'", stderr)

    def test_missing_frontend_importer_fails(self) -> None:
        """Dropping the frontend importer cannot hide frontend dependencies from the gate."""
        root = self.temporary_root()
        make_valid_repo(root)
        write(root / "pnpm-lock.yaml", LOCKFILE.split("  frontend:\n", 1)[0] + "packages: {}\n\nsnapshots: {}\n")

        result, _, stderr = run_guard(root)

        self.assertEqual(result, 1)
        self.assertIn("no lockfile importer for workspace: frontend", stderr)

    def test_malformed_root_lockfile_fails_before_install(self) -> None:
        """Root lockfile conflict markers are rejected before any frozen install."""
        root = self.temporary_root()
        make_valid_repo(root)
        write(
            root / "pnpm-lock.yaml",
            LOCKFILE.replace(
                "  frontend:\n",
                conflict_block("  frontend:\n", "  other:\n", end_label="branch") + "  frontend:\n",
            ),
        )

        result, _, stderr = run_guard(root)

        self.assertEqual(result, 1)
        self.assertIn("unresolved Git conflict marker in dependency file", stderr)
        self.assertIn("pnpm-lock.yaml:", stderr)

    def test_pnpm_pin_drift_fails(self) -> None:
        """package.json and the CI Dockerfile must pin the same pnpm version."""
        root = self.temporary_root()
        make_valid_repo(root)
        write(root / "Dockerfile.ci", "FROM base\nRUN npm install -g pnpm@9.0.0\n")

        result, _, stderr = run_guard(root)

        self.assertEqual(result, 1)
        self.assertIn("pnpm pin does not match packageManager pin 10.15.0", stderr)
        self.assertIn("lockfileVersion 9.0 does not match pinned pnpm 9.0.0", stderr)

    def test_duplicate_manifest_keys_fail(self) -> None:
        """A manifest with a repeated dependency key is not silently accepted."""
        root = self.temporary_root()
        make_valid_repo(root)
        write(
            root / "package.json",
            '{"packageManager": "pnpm@10.15.0", "dependencies": {}, "dependencies": {}}\n',
        )

        result, _, stderr = run_guard(root)

        self.assertEqual(result, 1)
        self.assertIn("invalid package.json", stderr)

    def test_exact_head_and_merge_candidate_trees_are_validated_separately(self) -> None:
        """A clean base does not validate a malformed PR head or its merge tree."""
        root = self.temporary_root()
        init = root / "repo"
        init.mkdir()
        git(init, "init", "--quiet", "--initial-branch=main")
        git(init, "config", "user.name", "Dependency Guard Test")
        git(init, "config", "user.email", "dependency-guard@example.invalid")
        make_valid_repo(init)
        base_sha = commit_all(init, "valid base workspace")

        git(init, "checkout", "--quiet", "-b", "candidate")
        write(init / "frontend/pnpm-lock.yaml", HISTORICAL_NESTED_LOCKFILE)
        candidate_sha = commit_all(init, "malformed candidate lockfile")

        git(init, "checkout", "--quiet", "main")
        write(init / "README.md", "Unrelated base change.\n")
        commit_all(init, "unrelated base change")
        git(init, "merge", "--quiet", "--no-ff", "candidate", "-m", "merge candidate")
        merge_sha = git(init, "rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(base_sha, candidate_sha)
        self.assertNotEqual(candidate_sha, merge_sha)

        for label, sha, expected in (
            ("base", base_sha, 0),
            ("candidate", candidate_sha, 1),
            ("merge", merge_sha, 1),
        ):
            with self.subTest(tree=label, sha=sha):
                tree = root / label
                tree.mkdir()
                with subprocess.Popen(
                    ["git", "-C", str(init), "archive", sha],
                    stdout=subprocess.PIPE,
                ) as archive:
                    assert archive.stdout
                    subprocess.run(
                        ["tar", "-x", "-C", str(tree)],
                        stdin=archive.stdout,
                        check=True,
                    )
                    archive.stdout.close()
                    archive.wait()
                result, _, stderr = run_guard(tree)
                self.assertEqual(result, expected, stderr)

    def test_required_ci_gate_covers_fast_path_summary_and_exact_head(self) -> None:
        """The required job runs on every event and CI Summary rejects every non-success result."""
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        job_block = workflow.split("  dependency-integrity:\n", 1)[1].split(
            "\n  check-all-jobs:\n", 1
        )[0]
        summary = workflow.split("  check-all-jobs:\n", 1)[1]
        needs_line = next(line for line in summary.splitlines() if "needs:" in line)

        self.assertNotIn("factory-scope", job_block)
        self.assertNotIn("fast_only", job_block)
        self.assertIn("python3 -m unittest discover -s tests -p test_dependency_integrity.py", job_block)
        self.assertIn("python3 scripts/check_dependency_integrity.py", job_block)
        self.assertIn("corepack enable", job_block)
        self.assertIn("pnpm install --frozen-lockfile", job_block)
        self.assertIn('git archive "$HEAD_SHA"', job_block)
        self.assertIn('python3 scripts/check_dependency_integrity.py --root "$head_tree"', job_block)
        self.assertIn("dependency-integrity", needs_line)
        self.assertIn('"${{ needs.dependency-integrity.result }}"', summary)
        self.assertGreaterEqual(summary.count('"${{ needs.dependency-integrity.result }}"'), 2)
        self.assertIn(
            '[ "${{ needs.dependency-integrity.result }}" != "success" ]',
            summary,
        )


if __name__ == "__main__":
    unittest.main()
