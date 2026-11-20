"""Regression coverage for repository isolation during pre-push validation."""

import os
import subprocess
from pathlib import Path


def test_pre_push_clears_repository_local_git_environment(tmp_path: Path) -> None:
    """Run the lint-only hook while ensuring no test gates run and Git env is isolated."""
    hook = Path(__file__).resolve().parents[1] / ".githooks" / "pre-push"
    local_variables = subprocess.check_output(
        ["git", "rev-parse", "--local-env-vars"], text=True
    ).splitlines()
    environment = {key: value for key, value in os.environ.items() if key not in local_variables}
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], env=environment, check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
        env=environment,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test"],
        env=environment,
        check=True,
    )
    tree = subprocess.check_output(
        ["git", "-C", str(repository), "mktree"], input="", text=True, env=environment
    ).strip()
    commit = subprocess.check_output(
        ["git", "-C", str(repository), "commit-tree", tree, "-m", "seed"],
        text=True,
        env=environment,
    ).strip()
    subprocess.run(
        ["git", "-C", str(repository), "update-ref", "HEAD", commit],
        env=environment,
        check=True,
    )

    (repository / "pyproject.toml").touch()
    (repository / "frontend" / "node_modules").mkdir(parents=True)
    (repository / "scripts").mkdir()
    (repository / "scripts" / "lint.sh").write_text("""#!/bin/bash
set -e

# Check for leaked Git repository-local environment variables
# These variables can escape from the parent worktree into sub-repositories
# created by the pre-push hook, causing tests to pass incorrectly.
for variable in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_CONFIG_PARAMETERS; do
    if [[ -v "$variable" ]]; then
        echo "Leaked $variable" >&2
        LEAKED=1
    fi
done

# Signal that Git environment checks completed successfully
printf "Git env checks completed\\n" >> "$GATE_LOG"

exit 0
""")
    tools_directory = tmp_path / "tools"
    tools_directory.mkdir()
    for tool in ("python", "pnpm"):
        executable = tools_directory / tool
        executable.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            "for variable in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_CONFIG_PARAMETERS; do\n"
            '  if [[ -v "$variable" ]]; then echo "Leaked $variable" >&2; exit 1; fi\n'
            "done\n"
            'printf "%s\\n" "$*" >> "$GATE_LOG"\n'
        )
        executable.chmod(0o755)
    gate_log = tmp_path / "gates.log"
    environment.update(
        {
            "PATH": f"{tools_directory}:{environment['PATH']}",
            "VIRTUAL_ENV": str(tmp_path / "venv"),
            "GIT_DIR": str(repository / ".git"),
            "GIT_WORK_TREE": str(repository),
            "GIT_INDEX_FILE": str(repository / ".git" / "index"),
            "GIT_CONFIG_PARAMETERS": "'core.hooksPath'='/unexpected/hooks'",
            "GATE_LOG": str(gate_log),
        }
    )
    result = subprocess.run(
        ["bash", str(hook)], cwd=repository, env=environment, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # Assert that the lint script's Git environment checks ran (gate_log has content)
    assert gate_log.exists() and gate_log.read_text().strip() != "", (
        f"Git environment checks did not run; gate_log is empty or missing. "
        f"Content: {gate_log.read_text()!r}"
    )
    # Assert that no test commands ran; gate_log should only contain lint-related messages
    gate_log_content = gate_log.read_text()
    assert "pytest" not in gate_log_content, (
        "Test commands (pytest) should not run during pre-push lint; found in gate_log"
    )
    assert "vitest" not in gate_log_content, (
        "Test commands (vitest) should not run during pre-push lint; found in gate_log"
    )
