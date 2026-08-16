from pathlib import Path


def test_dispatcher_drains_ready_factory_prs_with_exact_head_gates() -> None:
    dispatcher = Path('.github/workflows/free-model-factory-dispatch.yml').read_text(encoding='utf-8')

    assert 'Drain exact-head ready factory PRs' in dispatcher
    assert "--label 'factory:ready'" in dispatcher
    assert 'checks: read' in dispatcher
    assert 'contents: write' in dispatcher
    assert 'current_head_review_blockers' in dispatcher
    assert '.state == "CHANGES_REQUESTED" and .commit_id == $head' in dispatcher
    assert 'reviewThreads(first:100)' in dispatcher
    assert 'gh pr checks "$pr" --repo "$GITHUB_REPOSITORY" --required' in dispatcher
    assert '[[ "$head" == "$expected_head" ]]' in dispatcher
    assert '--merge --match-head-commit "$head"' in dispatcher


def test_ready_drain_reuses_dispatch_runner_without_blocking_dispatch() -> None:
    dispatcher = Path('.github/workflows/free-model-factory-dispatch.yml').read_text(encoding='utf-8')

    assert '\n  dispatch:\n' in dispatcher
    assert '\n  drain-ready:\n' not in dispatcher
    assert 'continue-on-error: true' in dispatcher
    assert dispatcher.index('Drain exact-head ready factory PRs') < dispatcher.index('Resolve and dispatch fixed workers')
