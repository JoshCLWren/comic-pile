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
    assert permission["edit"] == "deny"
    assert permission["task"] == "deny"
    assert permission["external_directory"] == "deny"
    assert permission["question"] == "deny"
    assert permission["bash"]["*"] == "deny"


def test_release_writer_only_calls_validated_helper() -> None:
    """The only allowed command must be the credential-holding helper script."""
    permission = _load_agent_permission()
    allowed_bash = {
        command for command, decision in permission["bash"].items() if decision == "allow"
    }
    assert allowed_bash == {"python scripts/release_writer.py *"}


def test_release_writer_has_no_github_metadata_mutation_command() -> None:
    """Reject merge, label, comment, edit, or raw gh api commands."""
    permission = _load_agent_permission()
    allowed_bash = {
        command for command, decision in permission["bash"].items() if decision == "allow"
    }
    for command in allowed_bash:
        assert "gh api" not in command
        assert "merge" not in command
        assert "label" not in command
        assert "comment" not in command
        assert "git push" not in command


def test_release_writer_helper_documents_all_commands() -> None:
    """Every documented helper command must exist in the release-writer script."""
    helper_text = RELEASE_WRITER_HELPER.read_text(encoding="utf-8")
    agent_text = RELEASE_WRITER_AGENT.read_text(encoding="utf-8")
    for command in ("recent", "check", "publish", "skip", "retract", "pr", "files", "issues"):
        assert f'command == "{command}"' in helper_text, f"missing {command} handler"
        assert f"release_writer.py {command}" in agent_text, f"missing {command} docs"


def test_release_writer_all_read_helpers_are_get_only(monkeypatch) -> None:
    """All read-only helper commands (_recent, _pr, _files, _issues) use GET only."""
    import io
    import json as jsonlib

    from scripts import release_writer

    monkeypatch.setenv("GH_TOKEN", "test-token")

    def make_fake():
        # Provide enough responses for any call order
        available = {
            "pulls": jsonlib.dumps(
                [{"number": 1, "merged_at": "2026-01-01T00:00:00Z",
                  "merge_commit_sha": "abc", "title": "PR"}]
            ).encode(),
            "pull": jsonlib.dumps(
                {"number": 1082, "title": "PR #1082", "body": "Closes #1070.",
                 "merged": True, "merged_at": "2026-08-11T00:00:00Z",
                 "merge_commit_sha": "abc123", "state": "closed",
                 "html_url": "https://example.com", "user": {"login": "t"}}
            ).encode(),
            "files": jsonlib.dumps(
                [{"filename": "x.py", "status": "modified",
                  "additions": 1, "deletions": 0}]
            ).encode(),
            "issues": jsonlib.dumps(
                {"number": 1082, "title": "PR #1082", "body": "Closes #1070."}
            ).encode(),
        }

        def fake_urlopen(request, timeout=20):
            assert request.get_method() == "GET", f"Expected GET, got {request.get_method()}"
            assert getattr(request, "data", None) is None, "GitHub reads must not send a body"
            url = str(getattr(request, "full_url", getattr(request, "url", "unknown")))
            key = "files" if "/files" in url else ("pull" if "/pulls/" in url else ("pulls" if "/pulls?" in url else "issues"))
            body_bytes = available.get(key, available["pull"])
            return io.BytesIO(body_bytes)

        return fake_urlopen

    monkeypatch.setattr(release_writer.urllib.request, "urlopen", make_fake())

    # Exercise all four read-only helpers
    release_writer._recent("JoshCLWren/comic-pile", "1")
    release_writer._pr("JoshCLWren/comic-pile", "1082")
    release_writer._files("JoshCLWren/comic-pile", "1082")
    release_writer._issues("JoshCLWren/comic-pile", "1082")
