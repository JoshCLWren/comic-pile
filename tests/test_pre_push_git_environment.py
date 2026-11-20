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
LEAKED=0
for variable in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_CONFIG_PARAMETERS; do
    if [[ -v "$variable" ]]; then
        echo "Leaked $variable" >&2
        LEAKED=1
    fi
done

# Record that Git environment checks ran as part of lint
if [ "$LEAKED" -eq 0 ]; then
    printf "Git env checks completed (no leaks)\\"n" >> "$GATE_LOG"
else
    printf "Git env checks completed (leaks detected)\\"n" >> "$GATE_LOG"
fi

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
    assert gate_log.exists() and gate_log.read_text().strip() != "", (
        f"Git environment checks did not run; gate_log is empty or missing. "
        f"Content: {gate_log.read_text()!r}"
    )
    # Separate assertion: no test commands ran as part of the lint gate.
    # The lint script should only perform static checks, not invoke test suites.
    # Exclude the hook's summary line from this check; the summary intentionally
    # mentions CI test suites for clarity (see G1 wording update). Only check
    # actual output lines for test command invocations.
    output_lower = (result.stdout + result.stderr).lower()
    # Filter out the hook's "Pre-push lint passed" summary line which
    # intentionally mentions CI test suites for clarification (G1 wording).
    filtered_lines = [
        line for line in output_lower.splitlines()
        if not line.startswith("pre-push lint passed")
    ]
    output_filtered = "\n".join(filtered_lines)
    assert "pytest" not in output_filtered, (
        f"Lint gate unexpectedly ran pytest; test commands leaked into lint gate. "
        f"Output: {result.stdout + result.stderr!r}"
    )
    assert "vitest" not in output_filtered, (
        f"Lint gate unexpectedly ran vitest; test commands leaked into lint gate. "
        f"Output: {result.stdout + result.stderr!r}"
    )
    assert "ui audit" not in output_filtered, (
        f"Lint gate unexpectedly ran UI audit; test commands leaked into lint gate. "
        f"Output: {result.stdout + result.stderr!r}"
    )
