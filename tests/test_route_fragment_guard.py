"""Tests for the fragment-only pull-request guard.

The guard in ``scripts/check_route_fragment_guard.py`` fails PRs that
hand-edit bot-owned generation artifacts. Route PRs must touch only
``docs/api/route-fragments/*.json`` source fragments (excluding the
generated rewrite artifact). These tests pin the classifier, the
``AGENTS.md`` marked-block comparison, and the shipped workflows.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.check_route_fragment_guard import (
    agents_block_changed,
    extract_agents_block,
    find_generated_violations,
    is_generated_path,
    is_source_fragment,
)


ROOT = Path(__file__).resolve().parents[1]


def test_generated_paths_are_bot_owned() -> None:
    """All three generated artifacts are classified as bot-owned."""
    assert is_generated_path("vercel.json")
    assert is_generated_path("docs/api/v2-route-inventory.json")
    assert is_generated_path("docs/api/route-fragments/vercel-rewrites.json")


def test_vercel_rewrites_is_generated_despite_fragment_directory() -> None:
    """The rewrite artifact is generated, not a source fragment."""
    assert not is_source_fragment("docs/api/route-fragments/vercel-rewrites.json")
    assert is_generated_path("docs/api/route-fragments/vercel-rewrites.json")


def test_source_fragments_are_contributor_editable() -> None:
    """Family fragments are the only editable route source."""
    assert is_source_fragment("docs/api/route-fragments/threads.json")
    assert is_source_fragment("docs/api/route-fragments/creators.json")
    assert not is_generated_path("docs/api/route-fragments/threads.json")
    assert not is_source_fragment("vercel.json")


def test_agents_path_alone_is_not_unconditionally_generated() -> None:
    """AGENTS.md is editable outside the generated burndown markers."""
    assert not is_generated_path("AGENTS.md")


def test_find_violations_flags_generated_files() -> None:
    """A PR touching vercel.json fails the fragment-only contract."""
    violations = find_generated_violations(
        ["docs/api/route-fragments/threads.json", "vercel.json"],
        agents_changed=False,
    )
    assert violations == ["vercel.json"]


def test_find_violations_allows_fragment_only_pr() -> None:
    """Fragment-only and unrelated PRs pass the guard."""
    violations = find_generated_violations(
        ["docs/api/route-fragments/threads.json", "app/api/foo.py"],
        agents_changed=False,
    )
    assert violations == []


def test_find_violations_flags_agents_block_change() -> None:
    """Changing inside the burndown markers fails even with other edits."""
    violations = find_generated_violations(
        ["AGENTS.md", "docs/api/route-fragments/threads.json"],
        agents_changed=True,
    )
    assert "AGENTS.md (route-burndown block)" in violations


def test_agents_block_changed_detects_marked_edit() -> None:
    """Edits between the route-burndown markers are detected."""
    base = (
        "# AGENTS.md\n\n<!-- route-burndown:begin -->\nold\n"
        "<!-- route-burndown:end -->\n\n## Policy\n"
    )
    head = (
        "# AGENTS.md\n\n<!-- route-burndown:begin -->\nnew\n"
        "<!-- route-burndown:end -->\n\n## Policy\n"
    )
    assert agents_block_changed(base, head) is True


def test_agents_block_changed_ignores_outside_block_edit() -> None:
    """Guidance outside the markers survives the guard."""
    base = (
        "# AGENTS.md\n\n<!-- route-burndown:begin -->\nsame\n"
        "<!-- route-burndown:end -->\n\n## Policy\nold\n"
    )
    head = (
        "# AGENTS.md\n\n<!-- route-burndown:begin -->\nsame\n"
        "<!-- route-burndown:end -->\n\n## Policy\nnew guidance\n"
    )
    assert agents_block_changed(base, head) is False
    assert extract_agents_block(base) == extract_agents_block(head)


def test_agents_block_changed_missing_marker_side() -> None:
    """A missing block on one side counts as a change."""
    with_markers = "a\n<!-- route-burndown:begin -->\nx\n<!-- route-burndown:end -->\n"
    without = "a\n"
    assert agents_block_changed(with_markers, without) is True
    assert extract_agents_block(without) is None


def test_regenerate_workflow_triggers_on_fragment_push() -> None:
    """Post-merge regen runs on main when fragments change."""
    workflow_path = ROOT / ".github" / "workflows" / "regenerate-routes.yml"
    assert workflow_path.exists()
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    # PyYAML parses the YAML 1.1 `on` key as boolean True.
    on = workflow.get("on", workflow.get(True))
    assert isinstance(on, dict)
    push = on.get("push")
    assert isinstance(push, dict)
    branches = push.get("branches")
    assert isinstance(branches, list)
    assert "main" in branches
    paths = push.get("paths")
    assert isinstance(paths, list)
    assert "docs/api/route-fragments/*.json" in paths
    assert "vercel.json" not in paths
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    assert jobs  # at least one regeneration job is defined
    permissions = workflow.get("permissions")
    assert isinstance(permissions, dict)
    assert permissions.get("contents") == "write"


def test_guard_workflow_runs_on_pull_request() -> None:
    """The fragment-only guard gates every pull request."""
    workflow_path = ROOT / ".github" / "workflows" / "route-fragment-guard.yml"
    assert workflow_path.exists()
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    # PyYAML parses the YAML 1.1 `on` key as boolean True.
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, dict):
        assert "pull_request" in on
    elif isinstance(on, list):
        assert "pull_request" in on
    else:
        pytest.fail("guard workflow must trigger on pull_request")


@pytest.mark.parametrize(
    "path",
    [
        "vercel.json",
        "docs/api/v2-route-inventory.json",
        "docs/api/route-fragments/vercel-rewrites.json",
    ],
)
def test_generated_paths_list_matches_guard_contract(path: str) -> None:
    """Guard contract covers every bot-owned artifact."""
    assert is_generated_path(path)
