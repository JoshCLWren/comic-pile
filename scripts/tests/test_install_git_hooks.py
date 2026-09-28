"""Regression coverage for the ComicPile git-hook installer."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install-git-hooks.sh"


class InstallGitHooksTests(unittest.TestCase):
    """Verify hook installation preserves user-owned originals."""

    def test_repeated_install_keeps_first_user_hook_backups(self) -> None:
        """Installing twice must not replace original hooks in the backup directory."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            hooks = repository / ".git" / "hooks"
            versioned_hooks = repository / ".githooks"
            hooks.mkdir(parents=True)
            versioned_hooks.mkdir()

            original_contents = {
                "pre-commit": "#!/bin/sh\necho user-pre-commit\n",
                "pre-push": "#!/bin/sh\necho user-pre-push\n",
                "prepare-commit-msg": "#!/bin/sh\necho user-prepare\n",
            }
            installed_contents = {
                "pre-commit": "#!/bin/sh\necho comic-pile-pre-commit\n",
                "pre-push": "#!/bin/sh\necho comic-pile-pre-push\n",
                "prepare-commit-msg": "#!/bin/sh\necho comic-pile-prepare\n",
            }

            for hook_name, content in original_contents.items():
                (hooks / hook_name).write_text(content, encoding="utf-8")
            for hook_name, content in installed_contents.items():
                (versioned_hooks / hook_name).write_text(content, encoding="utf-8")

            local_installer = repository / "install-git-hooks.sh"
            shutil.copy2(INSTALLER, local_installer)

            subprocess.run(["bash", str(local_installer)], cwd=repository, check=True)
            subprocess.run(["bash", str(local_installer)], cwd=repository, check=True)

            backups = hooks / "comic-pile-originals"
            for hook_name, original_content in original_contents.items():
                self.assertEqual(
                    (backups / hook_name).read_text(encoding="utf-8"),
                    original_content,
                )
                self.assertEqual(
                    (hooks / hook_name).read_text(encoding="utf-8"),
                    installed_contents[hook_name],
                )

    def test_installs_into_common_git_directory_from_linked_worktree(self) -> None:
        """A linked worktree has a .git file, not a directory."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            worktree = root / "worktree"
            subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.name", "Test User"],
                check=True,
            )
            (repository / "seed").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "seed"], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "commit", "-m", "seed"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "worktree", "add", "-b", "test", str(worktree)],
                check=True,
                capture_output=True,
            )
            shutil.copytree(ROOT / ".githooks", worktree / ".githooks")
            shutil.copy2(INSTALLER, worktree / "install-git-hooks.sh")

            subprocess.run(
                ["bash", "install-git-hooks.sh"], cwd=worktree, check=True, capture_output=True
            )

            self.assertTrue((repository / ".git" / "hooks" / "pre-commit").is_file())

    def test_pre_push_dependency_install_is_non_interactive(self) -> None:
        """Git hooks cannot answer pnpm's reinstall confirmation prompt."""
        pre_push = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")

        self.assertIn("CI=1 pnpm install --frozen-lockfile", pre_push)


if __name__ == "__main__":
    unittest.main()
