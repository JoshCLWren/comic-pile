"""Regression coverage for the factory status GitHub Pages workflow."""

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "factory-status-pages.yml"


def test_pages_workflow_uses_supported_first_deploy_configuration() -> None:
    """Keep the Pages workflow compatible with repositories enabled for Actions publishing."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "enablement: true" not in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "actions/configure-pages@v5" in workflow
    assert "actions/upload-pages-artifact@v4" in workflow
    assert "actions/deploy-pages@v5" in workflow
    assert "cancel-in-progress: false" in workflow


def test_pages_workflow_proves_the_public_dashboard_updated() -> None:
    """Do not treat an accepted Pages artifact as proof that the public site updated."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Verify Pages publishing mode" in workflow
    assert 'build_type\" != \"workflow\"' in workflow
    assert "Verify public dashboard freshness" in workflow
    assert "factory-pages-check=${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" in workflow
    assert "generated within the last 30 minutes" in workflow
