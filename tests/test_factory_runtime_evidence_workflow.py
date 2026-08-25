"""Regression coverage for durable factory attempt evidence in the runner workflow."""
from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "free-model-factory-run.yml"
)


def test_terminal_step_publishes_normalized_attempt_evidence():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "factory-attempt-outcome:v1" in workflow
    assert "Attempt outcome: %s" in workflow
    assert "attempt_outcome='success'" in workflow
    assert "attempt_outcome='unknown_failure'" in workflow


def test_terminal_step_preserves_newer_attempt_evidence():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "existing_run > GITHUB_RUN_ID" in workflow
    assert "Newer attempt evidence from run" in workflow
