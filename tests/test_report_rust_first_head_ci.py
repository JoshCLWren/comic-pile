"""Regression tests for conservative first-head Rust CI attribution."""

from __future__ import annotations

from scripts.report_rust_first_head_ci import first_head, markdown, provenance, result_for


def test_first_head_does_not_confuse_later_repair_success_with_first_failure() -> None:
    """Later green PR heads cannot erase first-head failures."""
    runs: list[dict[str, object]] = [
        {
            "head_sha": "repaired",
            "created_at": "2026-11-01T17:30:00Z",
            "conclusion": "success",
        },
        {
            "head_sha": "opening",
            "created_at": "2026-11-01T17:00:00Z",
            "conclusion": "failure",
        },
        {
            "head_sha": "opening",
            "created_at": "2026-11-01T17:00:02Z",
            "conclusion": "success",
        },
    ]
    sha, initial = first_head(runs)
    assert sha == "opening"
    assert len(initial) == 2
    assert result_for(initial) == "failed"


def test_cancelled_pending_and_unobserved_heads_are_not_counted_green() -> None:
    """Do not infer quality from missing or incomplete GitHub history."""
    assert result_for([]) == "no-runs"
    assert result_for([{"conclusion": "cancelled"}]) == "cancelled"
    assert result_for([{"conclusion": None}]) == "incomplete"
    assert result_for([{"conclusion": "success"}]) == "passed"


def test_model_and_worker_require_explicit_pr_body_provenance() -> None:
    """Never assign unlabeled coding to a guessed provider."""
    assert provenance("Model: glm-4.5-flash\nWorker: factory-54\n", "Model") == "glm-4.5-flash"
    assert provenance("Model: glm-4.5-flash\nWorker: factory-54\n", "Worker") == "factory-54"
    assert provenance("No model declaration", "Model") == "unknown"


def test_markdown_preserves_incomplete_bucket_and_unclassified_failure() -> None:
    """The model scorecard must not silently treat unknown runs as passed."""
    data: dict[str, object] = {
        "repository": "example/repo",
        "since": "2026-10-29",
        "coverage_limit": "bounded",
        "pull_requests": [
            {"number": 10, "model": "model-a", "first_head_result": "failed", "failed_jobs": ["Native Rust Roll"]},
            {"number": 11, "model": "model-a", "first_head_result": "no-runs", "failed_jobs": []},
        ],
    }
    output = markdown(data)
    assert "| model-a | 2 | 0 | 1 | 1 |" in output
    assert "PR #10" in output
    assert "unclassified" in output
