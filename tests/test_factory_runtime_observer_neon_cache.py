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


def test_existing_marker_uses_shared_cache_but_live_fallback_guards_new_creates() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    publisher = workflow.split("  publish-runtime-outcome:", 1)[1]
    marker = 'marker="<!-- factory-attempt-outcome:v1 worker=opencode-free-model-factory-'
    cache_lookup = 'from factory_completion_controller import registry_comments'
    miss = 'if [[ -z "$comment_id" ]]; then'
    full_scan = 'gh api --paginate "repos/${GITHUB_REPOSITORY}/issues/1093/comments?per_page=100"'
    live_recheck = 'gh api "repos/${GITHUB_REPOSITORY}/issues/comments/${comment_id}"'
    create = 'gh api --method POST "repos/${GITHUB_REPOSITORY}/issues/1093/comments"'
    assert marker in publisher
    assert publisher.index(cache_lookup) < publisher.index(miss) < publisher.index(full_scan)
    assert publisher.index(full_scan) < publisher.index(live_recheck) < publisher.index(create)
    assert "Newer attempt evidence from run" in publisher
    assert 'gh api --method PATCH "repos/${GITHUB_REPOSITORY}/issues/comments/${comment_id}"' in publisher
