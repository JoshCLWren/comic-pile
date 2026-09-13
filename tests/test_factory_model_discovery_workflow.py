"""Contract tests for the factory model discovery workflow."""

from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "factory-model-discovery.yml"
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
    assert "catalog_fixture" in workflow
