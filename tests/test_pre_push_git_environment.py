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
    (repository / "scripts" / "lint.sh").write_text("exit 0\n")
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
    # The hook should fail when leaked Git environment variables are present
    assert result.returncode != 0, f"Hook should fail due to leaked Git environment variables: {result.stdout} {result.stderr}"
    assert gate_log.exists(), "gate_log file should exist"
    assert "Leaked GIT_DIR" in gate_log.read_text(), "GIT_DIR leak not detected"
    assert "Leaked GIT_WORK_TREE" in gate_log.read_text(), "GIT_WORK_TREE leak not detected"
    assert "Leaked GIT_INDEX_FILE" in gate_log.read_text(), "GIT_INDEX_FILE leak not detected"
    assert "Leaked GIT_CONFIG_PARAMETERS" in gate_log.read_text(), "GIT_CONFIG_PARAMETERS leak not detected"
