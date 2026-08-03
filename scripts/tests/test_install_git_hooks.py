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


if __name__ == "__main__":
    unittest.main()
