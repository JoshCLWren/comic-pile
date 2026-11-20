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
        "#!/bin/bash\n"
        "set -eu\n"
        "for variable in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_CONFIG_PARAMETERS; do\n"
        '  if [[ -v "$variable" ]]; then echo "Leaked $variable" >&2; exit 1; fi\n'
        "done\n"
        'printf "%s\\n" "lint" >> "$GATE_LOG"\n'
    )
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
    recorded_gates = gate_log.read_text().splitlines() if gate_log.exists() else []
    assert recorded_gates == ["lint"], (
        f"only scripts/lint.sh may run on push; recorded gates: {recorded_gates!r}"
    )
    assert "Leaked " not in result.stderr, result.stderr


def test_pre_push_rejects_leaked_git_environment(tmp_path: Path) -> None:
    """Fail the lint gate when the hook stops clearing repository-local Git state."""
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
    subprocess.run(
        ["git", "-C", str(repository), "commit", "--allow-empty", "-m", "seed"],
        env=environment,
        check=True,
    )
    (repository / "pyproject.toml").touch()
    (repository / "frontend" / "node_modules").mkdir(parents=True)
    (repository / "scripts").mkdir()
    (repository / "scripts" / "lint.sh").write_text(
        "#!/bin/bash\n"
        "set -eu\n"
        "for variable in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_CONFIG_PARAMETERS; do\n"
        '  if [[ -v "$variable" ]]; then echo "Leaked $variable" >&2; exit 1; fi\n'
        "done\n"
        'printf "%s\\n" "lint" >> "$GATE_LOG"\n'
    )
    tools_directory = tmp_path / "tools"
    tools_directory.mkdir()
    pnpm = tools_directory / "pnpm"
    pnpm.write_text("#!/bin/bash\nexit 0\n")
    pnpm.chmod(0o755)
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

    hook_without_isolation = tmp_path / "pre-push-without-isolation"
    hook_without_isolation.write_text(
        hook.read_text().replace(
            'while IFS= read -r git_local_variable; do\n'
            '    unset "$git_local_variable"\n'
            "done < <(git rev-parse --local-env-vars)\n",
            "",
        )
    )
    assert hook_without_isolation.read_text() != hook.read_text()
    result = subprocess.run(
        ["bash", str(hook_without_isolation)],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Leaked GIT_DIR" in result.stderr


def test_pre_push_runs_no_product_test_gates(tmp_path: Path) -> None:
    """Keep product test suites out of the pre-push hook."""
    hook = Path(__file__).resolve().parents[1] / ".githooks" / "pre-push"
    local_variables = subprocess.check_output(
        ["git", "rev-parse", "--local-env-vars"], text=True
    ).splitlines()
    environment = {key: value for key, value in os.environ.items() if key not in local_variables}
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], env=environment, check=True)
    (repository / "pyproject.toml").touch()
    (repository / "frontend" / "node_modules").mkdir(parents=True)
    (repository / "scripts").mkdir()
    (repository / "scripts" / "lint.sh").write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "lint" >> "$GATE_LOG"\n'
    )
    tools_directory = tmp_path / "tools"
    tools_directory.mkdir()
    for tool in ("python", "pnpm"):
        executable = tools_directory / tool
        executable.write_text(
            "#!/bin/bash\n"
            'printf "%s\\n" "$*" >> "$GATE_LOG"\n'
        )
        executable.chmod(0o755)
    gate_log = tmp_path / "gates.log"
    environment.update(
        {
            "PATH": f"{tools_directory}:{environment['PATH']}",
            "VIRTUAL_ENV": str(tmp_path / "venv"),
            "GATE_LOG": str(gate_log),
        }
    )

    result = subprocess.run(
        ["bash", str(hook)], cwd=repository, env=environment, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stdout + result.stderr
    recorded_gates = gate_log.read_text().splitlines() if gate_log.exists() else []
    assert recorded_gates == ["lint"], recorded_gates
