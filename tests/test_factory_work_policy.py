"""Regression coverage for factory assignment review capacity and independence."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"
SPEC = importlib.util.spec_from_file_location(
    "factory_work_policy",
    SCRIPTS / "factory_work_policy.py",
)
assert SPEC is not None and SPEC.loader is not None
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)

Candidate = policy.Candidate


def candidate(
    *,
    kind: str,
    number: int,
    stage: str | None = None,
    producer: str | None = None,
    lane: int = 3,
) -> Candidate:
    """Build a deterministic candidate fixture."""
    return Candidate(
        kind=kind,
        number=number,
        lane=lane,
        priority=0,
        created_at="2026-08-16T00:00:00Z",
        stage=stage,
        producer_worker=producer,
    )


def test_producing_worker_cannot_receive_own_semantic_review():
    """Review assignment itself enforces producer/reviewer independence."""
    own_review = candidate(
        kind="pr",
        number=1390,
        stage="factory:review",
        producer="43",
    )
    issue = candidate(kind="issue", number=1500)
    ordered = policy.order_candidates_for_worker([own_review, issue], "43")
    assert own_review not in ordered
    assert ordered == [issue]


def test_producer_can_receive_repair_work_without_self_approving():
    """Independence applies to semantic approval, not ordinary repair."""
    repair = candidate(
        kind="pr",
        number=1390,
        stage="factory:changes-requested",
        producer="43",
    )
    ordered = policy.order_candidates_for_worker([repair], "43")
    assert ordered == [repair]


def test_reserved_review_worker_prefers_factory_review():
    """A stable minority of the fleet gives review dependable capacity."""
    assert policy.review_capacity_worker("6")
    review = candidate(kind="pr", number=1390, stage="factory:review", producer="43")
    issue = candidate(kind="issue", number=1500, lane=1)
    ordered = policy.order_candidates_for_worker([issue, review], "6")
    assert ordered[0] == review


def test_non_reserved_worker_preserves_product_capacity():
    """Ordinary workers keep product implementation moving alongside review."""
    assert not policy.review_capacity_worker("9")
    review = candidate(kind="pr", number=1390, stage="factory:review", producer="43")
    issue = candidate(kind="issue", number=1500, lane=5)
    ordered = policy.order_candidates_for_worker([review, issue], "9")
    assert ordered[0] == issue


def test_stage_precedence_is_deterministic_for_inconsistent_labels():
    """Transient contradictory labels never randomize semantic review classification."""
    labels = {"factory:ci", "factory:review", "factory:building"}
    assert policy.stage_of(labels) == "factory:review"
    assert policy.stage_of(reversed(sorted(labels))) == "factory:review"


def test_shared_producer_provenance_drives_assignment():
    """Assignment derives producer identity through the canonical review policy."""
    pr = {
        "headRefName": "factory/43-1386-opencode-free",
        "body": "Worker: opencode-free-model-factory-17",
    }
    assert policy.producer_worker_from_pr(pr) == "43"


def test_closed_pr_is_never_a_candidate():
    """Autonomous assignment never resurrects a closed PR."""
    pr = {
        "number": 1390,
        "state": "CLOSED",
        "isDraft": False,
        "labels": [
            {"name": "factory"},
            {"name": "factory:unowned"},
            {"name": "factory:review"},
        ],
        "headRefName": "factory/43-1386-opencode-free",
        "body": "Worker: opencode-free-model-factory-43",
        "createdAt": "2026-08-16T00:00:00Z",
    }
    assert not policy.pr_is_static_candidate(pr, {})


def test_plan_distinct_assignments_reserves_review_without_stopping_product():
    """One batch can assign review and implementation concurrently."""
    review = candidate(kind="pr", number=1390, stage="factory:review", producer="43")
    issue_a = candidate(kind="issue", number=1500)
    issue_b = candidate(kind="issue", number=1501)
    assignments = policy.plan_distinct_assignments(
        [review, issue_a, issue_b],
        ["6", "9"],
    )
    assert assignments["6"] == review
    assert assignments["9"].kind == "issue"
