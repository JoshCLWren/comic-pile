"""Regression coverage for provider-derived dispatcher smoke selection."""
from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "fixed-model-factory-dispatch.yml"
)


def test_push_smoke_workers_are_derived_from_current_provider_rows():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workers='[\"6\",\"39\",\"46\"]'" not in workflow
    assert "!seen[$2]++ {print $1}" in workflow
    assert '"$manifest"' in workflow
    assert ".github/scripts/factory_provider_candidates.py" in workflow
    assert ".github/scripts/factory_candidate_health.py" in workflow


def test_stale_run_cancellation_retries_transient_status_race():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "cancel_succeeded=false" in workflow
    assert "for _ in {1..15}; do" in workflow
    assert '[[ "$current_status" == completed ]]' in workflow
    assert '[[ "$current_status" == queued || "$current_status" == in_progress ]]' in workflow