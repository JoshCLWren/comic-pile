"""Lock the full-repo ruff/ty gate to the exact GitHub CI commands.

Path-filtered ruff or ty is how Cursor agents previously shipped lint and
typecheck failures. This module fails if CI, the local gate script, pre-commit
lint, or agent policy drift back to checking only changed files.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI_RUFF = "ruff check ."
CI_TY = "ty check --error-on-warning"
GATE_MARKER = "Path-filtered ruff or ty is not a valid CI substitute"


def _read(relative_path: str) -> str:
    """Read one repository file as UTF-8 text."""
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_ci_workflow_uses_full_repo_ruff_and_ty() -> None:
    """GitHub CI must keep the exact full-repo ruff and ty invocations."""
    ci = _read(".github/workflows/ci.yml")
    assert f"run: {CI_RUFF}" in ci
    assert f"run: {CI_TY}" in ci


def test_check_script_matches_ci_commands() -> None:
    """The local gate script must run the same commands CI runs."""
    script = _read("scripts/check-python-ci-lint.sh")
    assert CI_RUFF in script
    assert CI_TY in script
    assert 'ruff check "$@"' not in script
    assert 'ty check --error-on-warning "$@"' not in script
    assert "check-python-ci-lint.sh" in _read("Makefile")


def test_lint_sh_does_not_path_filter_ruff_or_ty() -> None:
    """Staged-only lint must still run full-repo ruff and ty."""
    script = _read("scripts/lint.sh")
    assert "scripts/check-python-ci-lint.sh" in script
    assert 'ruff check "${STAGED_PYTHON_FILE_LIST[@]}"' not in script
    assert 'ty check --error-on-warning "$file"' not in script


def test_pre_commit_runs_shared_lint() -> None:
    """The versioned pre-commit hook must invoke the shared lint script."""
    hook = _read(".githooks/pre-commit")
    assert "scripts/lint.sh --staged" in hook


def test_agent_policy_forbids_path_filtered_python_lint() -> None:
    """Standing agent docs must require the exact CI pair, not changed-file lint."""
    agents = _read("AGENTS.md")
    protocol = _read("docs/ISSUE_EXECUTION_PROTOCOL.md")
    skill = _read(".agents/skills/github-issue-kanban/SKILL.md")
    factory = _read("docs/AUTONOMOUS_FACTORY_POLICY.md")
    prompt = _read("prompts/agent-next-task.md")

    for document in (agents, protocol, skill, factory, prompt):
        assert CI_RUFF in document
        assert CI_TY in document
        assert GATE_MARKER in document
        assert "ruff check <changed-python-files>" not in document
        assert "on the changed files" not in document
