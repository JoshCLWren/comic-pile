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
    (repository / "scripts" / "lint.sh").write_text(
        """#!/bin/bash
set -euo pipefail

# The hook must isolate every child process from its repository-local Git state.
for variable in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_CONFIG_PARAMETERS; do
    if [[ -v "$variable" ]]; then
        echo "Leaked $variable" >&2
        exit 1
    fi
done

# Prove that the lint stub—and therefore the environment checks above—ran.
printf "lint\\n" >> "$LINT_LOG"
# Marker file: environment checks ran (no leaked Git variables).
touch "$CHECKS_RAN_MARKER"
"""
    )
    tools_directory = tmp_path / "tools"
    tools_directory.mkdir()
    for tool in ("python", "pnpm"):
        executable = tools_directory / tool
        executable.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            'printf "%s\\n" "$*" >> "$TEST_GATE_LOG"\n'
        )
        executable.chmod(0o755)
    lint_log = tmp_path / "lint.log"
    test_gate_log = tmp_path / "test-gates.log"
    checks_ran_marker = tmp_path / "checks-ran.marker"
    environment.update(
        {
            "PATH": f"{tools_directory}:{environment['PATH']}",
            "VIRTUAL_ENV": str(tmp_path / "venv"),
            "GIT_DIR": str(repository / ".git"),
            "GIT_WORK_TREE": str(repository),
            "GIT_INDEX_FILE": str(repository / ".git" / "index"),
            "GIT_CONFIG_PARAMETERS": "'core.hooksPath'='/unexpected/hooks'",
            "LINT_LOG": str(lint_log),
            "TEST_GATE_LOG": str(test_gate_log),
            "CHECKS_RAN_MARKER": str(checks_ran_marker),
        }
    )
    result = subprocess.run(
        ["bash", str(hook)], cwd=repository, env=environment, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert lint_log.exists(), "The lint stub and its Git environment checks did not run"
    assert lint_log.read_text() == "lint\n"
    assert not test_gate_log.exists() or test_gate_log.read_text() == "", (
        f"Product test gates ran during pre-push: {test_gate_log.read_text()!r}"
    )
    # Verify the environment checks within the lint stub actually ran,
    # not just that the lint script produced output.
    assert checks_ran_marker.exists(), (
        "Git environment checks within lint stub did not run; "
        "marker file was not created"
    )
