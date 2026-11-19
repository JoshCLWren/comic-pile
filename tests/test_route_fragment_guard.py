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

from scripts import check_route_fragment_guard as guard
from scripts.check_route_fragment_guard import (
    agents_block_changed,
    extract_agents_block,
    find_generated_violations,
    is_generated_path,
    is_source_fragment,
    is_untracked_generated_path,
)


ROOT = Path(__file__).resolve().parents[1]


def test_generated_paths_are_bot_owned() -> None:
    """Both tracked generated route artifacts are classified as bot-owned."""
    assert is_generated_path("vercel.json")
    assert is_generated_path("docs/api/v2-route-inventory.json")


def test_vercel_rewrites_is_generated_despite_fragment_directory() -> None:
    """The rewrite artifact is an untracked build output, not a source fragment."""
    assert not is_source_fragment("docs/api/route-fragments/vercel-rewrites.json")
    assert is_untracked_generated_path("docs/api/route-fragments/vercel-rewrites.json")


@pytest.mark.parametrize(
    ("path", "generated"),
    [
        ("frontend/src/generated/openapi.ts", True),
        ("frontend/src/generated/openapi.json", True),
        ("frontend/src/generated/nativeV2Client.ts", True),
        ("native/contracts/v2-runtime.openapi.json", True),
        ("native/contracts/same-path-runtime.openapi.json", True),
        ("native/contracts/python-legacy.openapi.json", False),
        ("native/contracts/roll-bootstrap-v1.openapi.json", False),
        ("native/contracts/README.md", False),
        ("frontend/src/services/api-queue.ts", False),
        ("docs/api/route-fragments/threads.json", False),
    ],
)
def test_untracked_generated_artifact_classification(path: str, generated: bool) -> None:
    """Gitignored build outputs are classified; frozen inputs and sources are not."""
    assert is_untracked_generated_path(path) is generated


def test_adding_untracked_generated_artifact_is_a_violation() -> None:
    """A PR that re-adds or edits a generated artifact fails the guard."""
    violations = find_generated_violations(
        ["frontend/src/generated/nativeV2Client.ts", "native/contracts/v2-runtime.openapi.json"],
        agents_changed=False,
    )
    assert violations == [
        "frontend/src/generated/nativeV2Client.ts",
        "native/contracts/v2-runtime.openapi.json",
    ]


def test_deleting_untracked_generated_artifact_is_allowed() -> None:
    """Removing a generated artifact from git (merge main, delete copies) passes."""
    deleted = frozenset(
        {"frontend/src/generated/openapi.ts", "native/contracts/v2-runtime.openapi.json"}
    )
    assert find_generated_violations(sorted(deleted), agents_changed=False, deleted_files=deleted) == []


def test_deleting_bot_owned_tracked_artifact_is_still_a_violation() -> None:
    """vercel.json stays tracked and bot-owned; a PR may not delete it."""
    assert find_generated_violations(
        ["vercel.json"], agents_changed=False, deleted_files=frozenset({"vercel.json"})
    ) == ["vercel.json"]


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


def _ci_workflow() -> dict:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    assert isinstance(workflow, dict)
    return workflow


def test_guard_is_a_job_in_ci_for_every_pull_request() -> None:
    """The guard runs inside ci.yml on every PR event, never path-filtered."""
    workflow = _ci_workflow()
    on = workflow.get("on", workflow.get(True))
    assert isinstance(on, dict)
    assert "pull_request" in on
    assert not (on["pull_request"] or {}).get("paths")
    assert not (on["pull_request"] or {}).get("paths-ignore")
    assert not (on["pull_request"] or {}).get("types")
    job = workflow["jobs"]["route-fragment-guard"]
    assert "if" not in job
    assert "needs" not in job
    text = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "scripts/check_route_fragment_guard.py" in text
    assert "--allow-generated" in text
    conditions = "\n".join(str(step.get("if", "")) for step in job["steps"])
    assert all("pull_request" in str(step.get("if", "")) for step in job["steps"][:])
    assert "automation/route-regeneration/" in conditions
    assert "github.event.pull_request.head.repo.full_name == github.repository" in conditions


def test_guard_is_required_by_ci_summary() -> None:
    """Removing the guard from CI Summary must fail this test."""
    summary = _ci_workflow()["jobs"]["check-all-jobs"]
    assert summary["name"] == "CI Summary"
    assert "route-fragment-guard" in summary["needs"]
    script = "\n".join(str(step.get("run", "")) for step in summary["steps"])
    assert 'needs.route-fragment-guard.result }}" != "success"' in script


def test_standalone_guard_workflow_is_gone() -> None:
    """The guard lives in ci.yml only; no duplicate non-required workflow."""
    assert not (ROOT / ".github" / "workflows" / "route-fragment-guard.yml").exists()


@pytest.mark.parametrize(
    "path",
    [
        "vercel.json",
        "docs/api/v2-route-inventory.json",
    ],
)
def test_generated_paths_list_matches_guard_contract(path: str) -> None:
    """Guard contract covers every bot-owned artifact."""
    assert is_generated_path(path)


def test_agents_comparison_uses_the_merge_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale base tip must not fail an outside-marker AGENTS.md edit."""
    block = "<!-- route-burndown:begin -->\nold counts\n<!-- route-burndown:end -->"
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        calls.append(args)
        if args == ("merge-base", "base-tip", "head"):
            return "merge-base-sha\n"
        if args == ("show", "merge-base-sha:AGENTS.md"):
            return f"intro\n{block}\nfooter old\n"
        if args == ("show", "head:AGENTS.md"):
            return f"intro\n{block}\nfooter new\n"
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(guard, "_git_text", fake_git)
    assert guard.agents_block_changed_for_refs("base-tip", "head") is False
    assert ("show", "merge-base-sha:AGENTS.md") in calls
    assert ("show", "base-tip:AGENTS.md") not in calls


def test_regeneration_scope_rejects_source_and_code_edits() -> None:
    """Bot-only PRs cannot smuggle an unrelated file past the guard."""
    violations = guard.regenerated_pr_violations(
        ["vercel.json", "docs/api/route-fragments/threads.json", "app/main.py"],
        "base",
        "head",
    )
    assert violations == ["app/main.py", "docs/api/route-fragments/threads.json"]


def test_regeneration_scope_requires_changed_artifacts() -> None:
    """Empty bot PRs do not satisfy the generated artifact contract."""
    assert guard.regenerated_pr_violations([], "base", "head")


def test_regeneration_agents_may_only_change_generated_block() -> None:
    """The automation may not alter handwritten AGENTS.md guidance."""
    before = (
        "# AGENTS\n<!-- route-burndown:begin -->\nold\n"
        "<!-- route-burndown:end -->\\nmanual rules\\n"
    )
    after = before.replace("old", "new")
    assert guard.regenerated_agents_only(before, after)
    assert not guard.regenerated_agents_only(before, after + "new manual rule\\n")
    assert not guard.regenerated_agents_only(before, "# AGENTS\\nno markers\\n")


def test_regeneration_workflow_creates_ci_gated_pr() -> None:
    """No route regeneration may directly push to protected main or skip CI."""
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/regenerate-routes.yml").read_text(encoding="utf-8")
    )
    on = workflow.get("on", workflow.get(True))
    assert ".github/workflows/regenerate-routes.yml" in on["push"]["paths"]
    assert on["schedule"]
    steps = workflow["jobs"]["regenerate"]["steps"]
    publish = next(step for step in steps if "regeneration PR" in step.get("name", ""))
    script = publish["run"]
    assert "PR_REBASE_TOKEN" in publish["env"]["GH_TOKEN"]
    assert "automation/route-regeneration/current" in script
    assert "gh pr create" in script
    assert "gh pr merge" in script and "--auto" in script
    assert "--force-with-lease" in script
    assert "[skip ci]" not in script
    assert "git push\n" not in script


def test_ci_summary_gates_regeneration_proof() -> None:
    """The required CI Summary must depend on regeneration reproducibility."""
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = ci["jobs"]["rust-ingress"]["steps"]
    proof = next(step for step in steps if step.get("name", "").startswith("Prove regeneration PR"))
    assert "--allow-generated" in proof["run"]
    assert "generate_vercel_routes.mjs --check" in proof["run"]
    assert "generate_route_burndown.mjs --check" in proof["run"]
    assert "rust-ingress" in ci["jobs"]["check-all-jobs"]["needs"]


def test_regeneration_auto_merge_dispatches_production_after_merge() -> None:
    """Only a real merged artifact PR may dispatch production via trusted main."""
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/regenerate-routes.yml").read_text(encoding="utf-8")
    )
    on = workflow.get("on", workflow.get(True))
    assert "closed" in on["pull_request_target"]["types"]
    publisher = workflow["jobs"]["regenerate"]
    assert publisher["permissions"]["actions"] == "write"
    script = publisher["steps"][-1]["run"]
    assert "trap dispatch_deploy_after_merges EXIT" in script
    assert "factory_dispatch_production_deploy" in script
    assert "DEPLOY_TOKEN" in script
    handler = workflow["jobs"]["deploy-after-regeneration"]
    assert handler["permissions"]["actions"] == "write"
    assert "github.event.pull_request.merged == true" in handler["if"]
    assert "automation/route-regeneration/current" in handler["if"]
    assert handler["steps"][0]["with"]["ref"] == "main"
    assert "factory_dispatch_production_deploy" in handler["steps"][-1]["run"]
