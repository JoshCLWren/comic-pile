"""Regression tests banning backup artifacts from version control (issue #1722).

Covers three acceptance criteria: zero tracked files matching backup patterns,
.gitignore coverage for common backup extensions, and a pre-commit hook that
rejects staged backup files while permitting their deletion (untracking).
"""

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_EXTENSIONS = ["*.bak", "*.backup", "*.orig", "*~"]


def _require_git() -> str:
    """Return the git executable path or skip when git is unavailable."""
    git_path = shutil.which("git")
    if git_path is None:
        pytest.skip(reason="git is not available")
    assert git_path is not None
    return git_path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command inside ``repo`` and return the completed process."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _git_ok(repo: Path, *args: str) -> str:
    """Run a git command inside ``repo``, assert success, and return stdout."""
    result = _git(repo, *args)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout.strip()


def _write_file(repo: Path, relative_path: str, content: str = "data\n") -> Path:
    """Write a file inside ``repo``, creating parent directories."""
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


@pytest.fixture()
def hook_repo(tmp_path: Path) -> Path:
    """Create a throwaway git repo with the repository's real pre-commit hook."""
    _require_git()
    repo = tmp_path / "hook-repo"
    repo.mkdir()

    assert _git(repo, "init", "-q").returncode == 0
    assert _git(repo, "config", "user.email", "factory@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Factory Test").returncode == 0
    assert _git(repo, "config", "commit.gpgsign", "false").returncode == 0

    # Stub out scripts/lint.sh so a passing commit proves the guard allowed it
    # rather than failing later in the lint stage for unrelated reasons.
    lint_stub = _write_file(repo, "scripts/lint.sh", "#!/usr/bin/env bash\nexit 0\n")
    lint_stub.chmod(lint_stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_source = REPO_ROOT / ".githooks" / "pre-commit"
    hook_target = hooks_dir / "pre-commit"
    shutil.copy(hook_source, hook_target)
    hook_target.chmod(
        hook_target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )

    # Seed a first commit via plumbing so HEAD exists without invoking hooks.
    keep = _write_file(repo, "keep.txt")
    sha = _git_ok(repo, "hash-object", "-w", "keep.txt")
    _git_ok(repo, "update-index", "--add", "--cacheinfo", f"100644,{sha},keep.txt")
    tree = _git_ok(repo, "write-tree")
    commit_sha = _git_ok(repo, "commit-tree", tree, "-m", "seed")
    branch = _git_ok(repo, "symbolic-ref", "--short", "HEAD")
    _git_ok(repo, "update-ref", f"refs/heads/{branch}", commit_sha)
    assert keep.exists()
    return repo


def test_repo_tracks_no_backup_files() -> None:
    """No tracked file may match common backup patterns."""
    _require_git()
    result = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(REPO_ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    backup_suffixes = {".bak", ".backup", ".orig"}
    tracked_matches = [
        name
        for name in result.stdout.splitlines()
        if name.endswith("~") or Path(name).suffix.lower() in backup_suffixes
    ]
    assert tracked_matches == []


def test_gitignore_covers_common_backup_extensions() -> None:
    """.gitignore must contain explicit patterns for every common backup form."""
    content = (REPO_ROOT / ".gitignore").read_text()
    patterns = {line.strip() for line in content.splitlines()}
    for extension in BACKUP_EXTENSIONS:
        assert extension in patterns, f".gitignore is missing {extension}"


@pytest.mark.parametrize(
    ("backup_name",),
    [
        ("artifact.bak",),
        ("artifact.backup",),
        ("artifact.orig",),
        ("artifact~",),
        ("ARTIFACT.BACKUP",),
        ("nested/dir/artifact.bak",),
    ],
)
def test_pre_commit_hook_blocks_staged_backup_files(
    hook_repo: Path, backup_name: str
) -> None:
    """Committing a staged backup file fails with the backup-ban error."""
    _write_file(hook_repo, backup_name)
    _git_ok(hook_repo, "add", backup_name)

    commit = _git(hook_repo, "commit", "-m", "add backup artifact")

    assert commit.returncode != 0, "pre-commit hook failed to block a backup file"
    combined_output = commit.stdout + commit.stderr
    assert "Backup files staged for commit" in combined_output
    assert backup_name in combined_output
    assert "are banned from this repository" in combined_output


def test_pre_commit_hook_allows_normal_files(hook_repo: Path) -> None:
    """Ordinary files still commit cleanly through the full hook."""
    _write_file(hook_repo, "feature.txt", "legitimate change\n")
    _git_ok(hook_repo, "add", "feature.txt")

    commit = _git(hook_repo, "commit", "-m", "add feature")

    assert commit.returncode == 0, f"expected clean commit: {commit.stdout} {commit.stderr}"


def test_pre_commit_hook_permits_untracking_existing_backup(hook_repo: Path) -> None:
    """Staged deletions of tracked backups pass so they can be untracked."""
    backup_name = "legacy.bak"
    _write_file(hook_repo, backup_name)
    blob = _git_ok(hook_repo, "hash-object", "-w", backup_name)
    _git_ok(hook_repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{backup_name}")
    tree = _git_ok(hook_repo, "write-tree")
    commit_sha = _git_ok(hook_repo, "commit-tree", tree, "-m", "track legacy backup")
    branch = _git_ok(hook_repo, "symbolic-ref", "--short", "HEAD")
    _git_ok(hook_repo, "update-ref", f"refs/heads/{branch}", commit_sha)

    _git_ok(hook_repo, "rm", "--cached", backup_name)
    assert (hook_repo / backup_name).exists(), "untracking must keep the file on disk"

    commit = _git(hook_repo, "commit", "-m", "untrack legacy backup")

    assert commit.returncode == 0, f"untracking a backup must be allowed: {commit.stderr}"
