"""Regression coverage for OmniRoute factory request observability."""

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/free-model-factory-run.yml"


def test_omniroute_requests_carry_github_correlation_headers() -> None:
    """Route records must be attributable to the originating Actions run."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert '"X-GitHub-Run-ID": $run_id' in workflow
    assert '"X-GitHub-Job": $job' in workflow
    assert '"X-GitHub-Workflow": $workflow' in workflow


def test_omniroute_lane_publishes_routing_summary() -> None:
    """The lane should expose actual provider/model selection in job output."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Report OmniRoute routing summary" in workflow
    assert "/api/usage/analytics?period=session" in workflow
    assert "provider=\\(.provider) model=\\(.model)" in workflow
    assert '>> "$GITHUB_STEP_SUMMARY"' in workflow
