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
