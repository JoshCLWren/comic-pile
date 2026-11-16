"""Contract tests for using Neon to avoid per-worker full comment scans."""
from pathlib import Path


WORKFLOW = Path(".github/workflows/fixed-model-runtime-observer.yml")


def test_only_trusted_workflow_run_publisher_receives_neon_cache() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    classifier, publisher = workflow.split("  publish-runtime-outcome:", 1)
    assert "factory-state-cache" not in classifier
    assert "NEON_API_KEY" not in classifier
    assert "github.event_name == 'workflow_run'" in publisher
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in publisher
    assert "ref: main" in publisher
    assert "uses: ./.github/actions/factory-state-cache" in publisher
    assert "if: steps.runtime.outputs.publish == 'true'" in publisher
    assert "secrets.NEON_API_KEY" in publisher


def test_observer_uses_compact_verified_marker_ids_and_cold_start_fallback() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    publisher = workflow.split("  publish-runtime-outcome:", 1)[1]
    assert 'export-model-exclusions' in publisher
    assert '.__attempt_id[0]' in publisher
    assert 'from factory_registry_ingest import marker_ids' in publisher
    assert 'remember_verified_markers' in publisher
    assert 'gh api --paginate --slurp "repos/${GITHUB_REPOSITORY}/issues/1093/comments?per_page=100"' not in publisher
    assert "Unable to verify attempt marker; leaving trusted Neon completion intact" in publisher
    assert "HTTP 404" in publisher
    assert 'from factory_completion_controller import registry_comments' not in publisher
    assert "Newer attempt evidence from run" in publisher
