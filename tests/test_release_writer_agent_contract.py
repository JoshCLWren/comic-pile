"""Tests for the dedicated release-writer agent read-only safety contract."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WRITER_AGENT = ROOT / ".opencode" / "agents" / "release-writer.md"
RELEASE_WRITER_HELPER = ROOT / "scripts" / "release_writer.py"


def _load_agent_permission() -> dict:
    """Load the release-writer agent's permission block from its frontmatter.

    Args:
        None.

    Returns:
        The parsed YAML permission mapping for the release-writer agent.
    """
    text = RELEASE_WRITER_AGENT.read_text(encoding="utf-8")
    assert text.startswith("---"), "release-writer agent must start with YAML frontmatter"
    _, frontmatter, _ = text.split("---", 2)
    config = yaml.safe_load(frontmatter)
    return config["permission"]


def test_release_writer_cannot_edit_or_run_arbitrary_shell_commands() -> None:
    """Require structural denial of edits and arbitrary shell execution."""
    permission = _load_agent_permission()

    assert permission["edit"] == "deny", "release-writer agent must not edit"
    assert permission["task"] == "deny", "release-writer agent must not task"
    assert permission["external_directory"] == "deny", "release-writer agent must not access external_directory"
    assert permission["question"] == "deny", "release-writer agent must not answer questions"


def test_release_writer_can_use_gh_api_get_pulls() -> None:
    """Verify the agent can make targeted gh API GET requests for PR inspection."""
    permission = _load_agent_permission()

    assert permission["bash"] is not None, "bash permissions must be configured"
    bash_perms = permission["bash"]
    assert any(
        v == "allow" for v in bash_perms.values()
    ), "bash must allow targeted gh api GET repos/*/pulls/*"


def test_release_writer_can_use_gh_api_get_issues() -> None:
    """Verify the agent can make targeted gh API GET requests for issue inspection."""
    permission = _load_agent_permission()

    assert permission["bash"] is not None, "bash permissions must be configured"
    bash_perms = permission["bash"]
    assert any(
        v == "allow" for v in bash_perms.values()
    ), "bash must allow targeted gh api GET repos/*/issues/*"


def test_release_writer_cannot_edit_source() -> None:
    """Ensure the agent cannot edit application source code."""
    permission = _load_agent_permission()

    assert permission["edit"] == "deny", "release-writer agent must not have edit permission"


def test_release_writer_cannot_mutate_labels() -> None:
    """Ensure the agent cannot mutate GitHub labels."""
    permission = _load_agent_permission()

    assert permission["external_directory"] == "deny", "release-writer agent must not access external_directory"
