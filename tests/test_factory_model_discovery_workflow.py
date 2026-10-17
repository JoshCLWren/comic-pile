"""Contract tests for the factory model discovery workflow."""

from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "factory-model-discovery.yml"
)
FACTORY_RUN = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "free-model-factory-run.yml"
)


def test_discovery_workflow_is_scheduled_and_dispatchable() -> None:
    """Operators can dispatch discovery; the schedule does not wait for Harvy."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "cron: '17 */6 * * *'" in workflow
    assert "factory_model_retirement.py" in workflow
    assert "factory/model-retirement" in workflow
    assert "validate-free-model-factories.py" in workflow


def test_discovery_uses_opencode_cli_not_omniroute_or_integrate_api() -> None:
    """Roster truth is OpenCode CLI catalogs, not OmniRoute or NVIDIA HTTP."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "opencode models nvidia" in workflow
    assert "integrate.api.nvidia.com" in workflow
    assert "never integrate.api.nvidia.com" in workflow
    assert "omniroute/auto" not in workflow
    assert "auto/best-free" not in workflow
    assert "OPENCODE_ZEN_API_KEY" in workflow
    assert "NVIDIA_API_KEY" in workflow
    assert "MISTRAL_API_KEY" in workflow
    assert "catalog_fixture" in workflow


def test_discovery_and_runner_use_unpinned_opencode_v2() -> None:
    """Both workflows use the current OpenCode 2 release, not repository pins."""
    discovery = WORKFLOW.read_text(encoding="utf-8")
    runner = FACTORY_RUN.read_text(encoding="utf-8")
    installer = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "scripts"
        / "install-opencode-v2.sh"
    ).read_text(encoding="utf-8")
    assert "@opencode/cli@latest" in installer
    assert "OpenCode 2 required" in installer
    for workflow in (discovery, runner):
        assert "bash .github/scripts/install-opencode-v2.sh" in workflow
        assert "OPENCODE_VERSION:" not in workflow
        assert "OPENCODE_LINUX_X64_SHA256:" not in workflow


def test_discovery_keeps_dynamic_opencode_workers_without_roster_churn() -> None:
    """New free models run immediately without generated roster PRs."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "--dynamic-opencode-free" in workflow
    assert "--no-add-unused-free" in workflow
    assert "steps.plan.outputs.retire" in workflow
    assert "steps.plan.outputs.add" not in workflow
    assert "ADD_UNUSED_FREE" not in workflow
    assert "factory/model-retirement" in workflow
    assert "PR_REBASE_TOKEN is required" in workflow


def test_discovery_consumes_nvidia_410_markers_from_issue_1093() -> None:
    """Discovery fetches the same #1093 comments the NVIDIA probe uses."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    runner = FACTORY_RUN.read_text(encoding="utf-8")

    assert "issues/1093/comments" in workflow
    assert "--retirement-comments" in workflow
    assert "factory-model-retired-410:v1" in workflow
    assert "retirement_marker='<!-- factory-model-retired-410:v1 -->'" in runner
    assert 'gh api --paginate "repos/${GITHUB_REPOSITORY}/issues/1093/comments?per_page=100"' in runner
