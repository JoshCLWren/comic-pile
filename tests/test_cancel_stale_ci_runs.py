"""Regression tests for stale pull-request CI cancellation."""

from scripts.cancel_stale_ci_runs import select_superseded_runs


def test_selects_only_older_active_runs_for_same_pull_request_branch() -> None:
    """Select older active pull-request runs only from the matching branch."""
    runs = [
        {
            "id": 10,
            "event": "pull_request",
            "head_branch": "factory/example",
            "head_sha": "old-queued",
            "status": "queued",
            "html_url": "https://example.test/runs/10",
        },
        {
            "id": 11,
            "event": "pull_request",
            "head_branch": "factory/example",
            "head_sha": "old-running",
            "status": "in_progress",
            "html_url": "https://example.test/runs/11",
        },
        {
            "id": 12,
            "event": "pull_request",
            "head_branch": "factory/example",
            "head_sha": "current",
            "status": "in_progress",
            "html_url": "https://example.test/runs/12",
        },
        {
            "id": 13,
            "event": "pull_request",
            "head_branch": "factory/example",
            "head_sha": "old-success",
            "status": "completed",
            "html_url": "https://example.test/runs/13",
        },
        {
            "id": 14,
            "event": "pull_request",
            "head_branch": "factory/other-pr",
            "head_sha": "other",
            "status": "queued",
            "html_url": "https://example.test/runs/14",
        },
        {
            "id": 15,
            "event": "push",
            "head_branch": "factory/example",
            "head_sha": "main-push",
            "status": "queued",
            "html_url": "https://example.test/runs/15",
        },
    ]

    selected = select_superseded_runs(
        runs,
        head_branch="factory/example",
        current_sha="current",
    )

    assert [run.run_id for run in selected] == [10, 11]
    assert [run.head_sha for run in selected] == ["old-queued", "old-running"]


def test_accepts_all_github_active_run_states_and_orders_by_run_id() -> None:
    """Recognize every active GitHub state and return runs in stable order."""
    runs = [
        {
            "id": run_id,
            "event": "pull_request",
            "head_branch": "factory/example",
            "head_sha": f"old-{status}",
            "status": status,
            "html_url": "",
        }
        for run_id, status in [
            (5, "waiting"),
            (2, "requested"),
            (4, "pending"),
            (1, "queued"),
            (3, "in_progress"),
        ]
    ]

    selected = select_superseded_runs(
        runs,
        head_branch="factory/example",
        current_sha="current",
    )

    assert [run.run_id for run in selected] == [1, 2, 3, 4, 5]


def test_ignores_malformed_workflow_run_payloads() -> None:
    """Ignore incomplete workflow-run records instead of selecting them."""
    selected = select_superseded_runs(
        [
            {},
            {"id": "not-an-integer"},
            {
                "id": 1,
                "event": "pull_request",
                "head_branch": None,
                "head_sha": None,
                "status": "queued",
            },
        ],
        head_branch="factory/example",
        current_sha="current",
    )

    assert selected == []
